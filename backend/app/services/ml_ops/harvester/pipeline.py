"""Dataset Harvester orchestrator, stratified 70/15/15 YOLO splitter, manifest generator & Celery task."""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.core.celery_app import celery_app
from app.core.logging import get_logger
from app.core.security import sanitize_filename
from app.core.sse import publish_job_event
from app.services.ml_ops.harvester.config import HARD_QUOTA_BYTES, HarvesterConfig
from app.services.ml_ops.harvester.processor import (
    ImageQualityProcessor,
    ImageRejectedError,
    ProcessedImage,
    TaxonomyMapper,
    YoloAnnotation,
)
from app.services.ml_ops.harvester.quota_manager import DiskQuotaManager, QuotaExceededError
from app.services.ml_ops.harvester.sources import (
    BaseSourceConnector,
    CadSymbolsConnector,
    HarvestedItem,
    HuggingFaceStreamingConnector,
    PublicYoloRepoConnector,
    WikimediaCommonsConnector,
    is_open_license,
)

logger = get_logger(__name__)


@dataclass(slots=True)
class _StagedLabeledSample:
    """In-memory buffer entry for stratified 70/15/15 split before atomic disk write."""

    item: HarvestedItem
    processed: ProcessedImage
    annotations: list[YoloAnnotation]
    primary_class_id: int


@dataclass(frozen=True, slots=True)
class HarvestSummary:
    """Final audit summary returned by DatasetHarvesterPipeline.run()."""

    output_dir: Path
    manifest_path: Path
    dataset_yaml_path: Path
    quota_reached: bool
    used_bytes: int
    max_bytes: int
    labeled_counts: dict[str, int]
    unlabeled_count: int
    cad_symbols_count: int
    rejected_counts: dict[str, int]
    counts_by_source: dict[str, int]
    counts_by_class: dict[str, int]


def _assign_stratified_splits(
    samples: list[_StagedLabeledSample],
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    seed: int = 42,
) -> dict[str, list[_StagedLabeledSample]]:
    """Deterministically stratify labeled samples into train (70%), val (15%), golden_test (15%)."""
    rng = random.Random(seed)
    by_class: dict[int, list[_StagedLabeledSample]] = defaultdict(list)
    for sample in samples:
        by_class[sample.primary_class_id].append(sample)

    splits: dict[str, list[_StagedLabeledSample]] = {
        "train": [],
        "val": [],
        "golden_test": [],
    }

    for _cid, group in sorted(by_class.items()):
        group_sorted = sorted(group, key=lambda s: s.processed.sha256)
        rng.shuffle(group_sorted)
        n = len(group_sorted)
        if n == 1:
            splits["train"].extend(group_sorted)
            continue
        if n == 2:
            splits["train"].append(group_sorted[0])
            splits["val"].append(group_sorted[1])
            continue

        n_val = max(1, int(round(n * val_ratio)))
        n_test = max(1, int(round(n * (1.0 - train_ratio - val_ratio))))
        n_train = max(1, n - n_val - n_test)
        # Rebalance if rounding overshot n
        while n_train + n_val + n_test > n:
            if n_test > 1:
                n_test -= 1
            elif n_val > 1:
                n_val -= 1
            else:
                n_train -= 1

        splits["train"].extend(group_sorted[:n_train])
        splits["val"].extend(group_sorted[n_train : n_train + n_val])
        splits["golden_test"].extend(group_sorted[n_train + n_val :])

    return splits


class DatasetHarvesterPipeline:
    """End-to-end public electrical dataset harvester respecting a strict <= 950 MB hard quota."""

    def __init__(
        self,
        config: HarvesterConfig | None = None,
        connectors: list[BaseSourceConnector] | None = None,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> None:
        self.config = config or HarvesterConfig()
        self.taxonomy = TaxonomyMapper(self.config.taxonomy_path)
        self.processor = ImageQualityProcessor(self.config)
        self.quota = DiskQuotaManager(
            root_dir=self.config.output_dir,
            max_bytes=self.config.max_bytes,
        )
        self._progress_callback = progress_callback
        self.connectors: list[BaseSourceConnector] = (
            connectors if connectors is not None else self._build_default_connectors()
        )

    def _build_default_connectors(self) -> list[BaseSourceConnector]:
        registry: dict[str, Callable[[], BaseSourceConnector]] = {
            "wikimedia": lambda: WikimediaCommonsConnector(self.config, self.taxonomy),
            "huggingface": lambda: HuggingFaceStreamingConnector(self.config, self.taxonomy),
            "public_yolo": lambda: PublicYoloRepoConnector(self.config, self.taxonomy),
            "cad_symbols": lambda: CadSymbolsConnector(self.config, self.taxonomy),
        }
        return [
            registry[name]()
            for name in self.config.enabled_sources
            if name in registry
        ]

    def _notify(self, pct: int, message: str) -> None:
        if self._progress_callback is not None:
            self._progress_callback(pct, message)

    def run(self, max_items_per_source: int | None = None) -> HarvestSummary:
        """Execute harvesting, quality filtering, deduplication, stratified split & manifest write."""
        out_dir = self.quota.root_dir
        unlabeled_dir = out_dir / "unlabeled"
        cad_dir = out_dir / "cad_symbols"
        unlabeled_dir.mkdir(parents=True, exist_ok=True)
        cad_dir.mkdir(parents=True, exist_ok=True)

        manifest_entries: list[dict[str, Any]] = []
        rejected_counts: dict[str, int] = defaultdict(int)
        counts_by_source: dict[str, int] = defaultdict(int)
        counts_by_class: dict[str, int] = defaultdict(int)
        staged_labeled: list[_StagedLabeledSample] = []

        unlabeled_count = 0
        cad_symbols_count = 0
        quota_reached = False
        per_source_limit = max_items_per_source or self.config.max_items_per_source

        self._notify(5, f"Iniciando coleta pública (cota rígida: {self.quota.max_bytes} bytes)...")

        for idx, connector in enumerate(self.connectors):
            if quota_reached or self.quota.is_exhausted:
                quota_reached = True
                break

            base_pct = 10 + int((idx / max(1, len(self.connectors))) * 65)
            self._notify(base_pct, f"Coletando fonte '{connector.source_name}'...")

            for item in connector.iter_items(limit=per_source_limit):
                if not is_open_license(item.license):
                    rejected_counts["non_open_license"] += 1
                    continue

                if item.media_kind == "cad_symbol":
                    try:
                        safe_name = sanitize_filename(item.filename, fallback_stem=item.item_id)
                        dest = cad_dir / safe_name
                        self.quota.write_bytes(dest, item.raw_bytes)
                        sha = hashlib.sha256(item.raw_bytes).hexdigest()
                        cad_symbols_count += 1
                        counts_by_source[item.source_name] += 1
                        manifest_entries.append(
                            {
                                "item_id": item.item_id,
                                "source": item.source_name,
                                "source_url": item.source_url,
                                "license": item.license,
                                "media_kind": "cad_symbol",
                                "split": "cad_symbols",
                                "relative_path": str(dest.relative_to(out_dir)).replace("\\", "/"),
                                "size_bytes": len(item.raw_bytes),
                                "sha256": sha,
                            }
                        )
                    except QuotaExceededError:
                        quota_reached = True
                        logger.info("harvester_quota_reached_graceful_stop", used_bytes=self.quota.used_bytes)
                        break
                    continue

                # Image processing in memory (validate magic, min res, blur, pHash dedup, resize 1280px JPEG 85)
                try:
                    processed = self.processor.process_bytes(item.raw_bytes)
                except ImageRejectedError as exc:
                    rejected_counts[exc.reason] += 1
                    continue

                if item.annotations:
                    # Estimate bytes needed for JPEG + YOLO txt label and reserve quota upfront
                    yolo_txt = "\n".join(ann.to_yolo_line() for ann in item.annotations) + "\n"
                    est_bytes = len(processed.jpeg_bytes) + len(yolo_txt.encode("utf-8"))
                    if not self.quota.can_allocate(est_bytes):
                        quota_reached = True
                        logger.info(
                            "harvester_quota_reached_before_labeled_stage",
                            used_bytes=self.quota.used_bytes,
                            needed=est_bytes,
                        )
                        break
                    self.quota.reserve(est_bytes)
                    staged_labeled.append(
                        _StagedLabeledSample(
                            item=item,
                            processed=processed,
                            annotations=item.annotations,
                            primary_class_id=item.annotations[0].class_id,
                        )
                    )
                else:
                    # Unlabeled image -> save directly to unlabeled/ within quota
                    dest = unlabeled_dir / f"{item.source_name}_{processed.sha256[:16]}.jpg"
                    try:
                        self.quota.write_bytes(dest, processed.jpeg_bytes)
                    except QuotaExceededError:
                        quota_reached = True
                        logger.info("harvester_quota_reached_graceful_stop", used_bytes=self.quota.used_bytes)
                        break
                    unlabeled_count += 1
                    counts_by_source[item.source_name] += 1
                    manifest_entries.append(
                        {
                            "item_id": item.item_id,
                            "source": item.source_name,
                            "source_url": item.source_url,
                            "license": item.license,
                            "media_kind": "image",
                            "split": "unlabeled",
                            "relative_path": str(dest.relative_to(out_dir)).replace("\\", "/"),
                            "width": processed.width,
                            "height": processed.height,
                            "size_bytes": len(processed.jpeg_bytes),
                            "sha256": processed.sha256,
                            "phash": processed.phash_hex,
                            "blur_score": processed.blur_score,
                        }
                    )

        # Stratified 70/15/15 split & atomic write of staged labeled samples
        self._notify(82, "Gerando split estratificado YOLO (70% train / 15% val / 15% golden_test)...")
        labeled_counts: dict[str, int] = {"train": 0, "val": 0, "golden_test": 0}
        split_buckets = _assign_stratified_splits(
            staged_labeled,
            train_ratio=self.config.train_ratio,
            val_ratio=self.config.val_ratio,
            seed=self.config.random_seed,
        )

        for split_name in ("train", "val", "golden_test"):
            img_dir = out_dir / "images" / split_name
            lbl_dir = out_dir / "labels" / split_name
            img_dir.mkdir(parents=True, exist_ok=True)
            lbl_dir.mkdir(parents=True, exist_ok=True)

            for sample in split_buckets[split_name]:
                stem = f"{sample.item.source_name}_{sample.processed.sha256[:16]}"
                img_dest = img_dir / f"{stem}.jpg"
                lbl_dest = lbl_dir / f"{stem}.txt"
                yolo_txt = "\n".join(ann.to_yolo_line() for ann in sample.annotations) + "\n"
                yolo_bytes = yolo_txt.encode("utf-8")

                # Release pre-reservation and perform tracked atomic writes
                self.quota.release(len(sample.processed.jpeg_bytes) + len(yolo_bytes))
                self.quota.write_bytes(img_dest, sample.processed.jpeg_bytes)
                self.quota.write_bytes(lbl_dest, yolo_bytes)

                labeled_counts[split_name] += 1
                counts_by_source[sample.item.source_name] += 1
                for ann in sample.annotations:
                    cls_name = self.taxonomy.classes.get(ann.class_id, str(ann.class_id))
                    counts_by_class[cls_name] += 1

                manifest_entries.append(
                    {
                        "item_id": sample.item.item_id,
                        "source": sample.item.source_name,
                        "source_url": sample.item.source_url,
                        "license": sample.item.license,
                        "media_kind": "image",
                        "split": split_name,
                        "relative_path": str(img_dest.relative_to(out_dir)).replace("\\", "/"),
                        "label_path": str(lbl_dest.relative_to(out_dir)).replace("\\", "/"),
                        "width": sample.processed.width,
                        "height": sample.processed.height,
                        "size_bytes": len(sample.processed.jpeg_bytes) + len(yolo_bytes),
                        "sha256": sample.processed.sha256,
                        "phash": sample.processed.phash_hex,
                        "blur_score": sample.processed.blur_score,
                        "classes": sorted(
                            {self.taxonomy.classes[a.class_id] for a in sample.annotations}
                        ),
                    }
                )

        # Write Ultralytics-ready dataset.yaml
        self._notify(92, "Gerando dataset.yaml e manifest.json de auditoria...")
        dataset_yaml_data = {
            "path": str(out_dir.resolve()),
            "train": "images/train",
            "val": "images/val" if labeled_counts["val"] > 0 else "images/train",
            "test": "images/golden_test" if labeled_counts["golden_test"] > 0 else "images/train",
            "names": {cid: cname for cid, cname in sorted(self.taxonomy.classes.items())},
        }
        dataset_yaml_path = self.quota.write_metadata_unchecked(
            out_dir / "dataset.yaml",
            yaml.safe_dump(dataset_yaml_data, sort_keys=False, allow_unicode=True),
        )

        # Write manifest.json with full audit trail
        manifest_payload = {
            "schema_version": "1.0.0",
            "generated_at": datetime.now(UTC).isoformat(),
            "quota_reached": quota_reached,
            "max_bytes": self.quota.max_bytes,
            "used_bytes": self.quota.used_bytes,
            "utilization_pct": self.quota.utilization_pct,
            "labeled_counts": labeled_counts,
            "unlabeled_count": unlabeled_count,
            "cad_symbols_count": cad_symbols_count,
            "rejected_counts": dict(rejected_counts),
            "counts_by_source": dict(counts_by_source),
            "counts_by_class": dict(counts_by_class),
            "samples": manifest_entries,
        }
        manifest_path = self.quota.write_metadata_unchecked(
            out_dir / "manifest.json",
            json.dumps(manifest_payload, indent=2, ensure_ascii=False),
        )

        self._notify(100, "Coleta pública concluída com sucesso.")
        return HarvestSummary(
            output_dir=out_dir,
            manifest_path=manifest_path,
            dataset_yaml_path=dataset_yaml_path,
            quota_reached=quota_reached,
            used_bytes=self.quota.used_bytes,
            max_bytes=self.quota.max_bytes,
            labeled_counts=labeled_counts,
            unlabeled_count=unlabeled_count,
            cad_symbols_count=cad_symbols_count,
            rejected_counts=dict(rejected_counts),
            counts_by_source=dict(counts_by_source),
            counts_by_class=dict(counts_by_class),
        )


@celery_app.task(
    name="app.services.ml_ops.harvester.pipeline.run_dataset_harvest_task",
    bind=True,
)
def run_dataset_harvest_task(
    self: Any,
    max_mb: int = 950,
    sources: list[str] | None = None,
    max_items_per_source: int = 1500,
) -> dict[str, Any]:
    """Celery task executed on `worker-ml` (`train_queue`) with live SSE progress updates."""
    job_id = str(self.request.id or "dataset-harvest")
    clamped_bytes = min(HARD_QUOTA_BYTES, max(1, max_mb) * 1024 * 1024)

    publish_job_event(
        job_id,
        "STARTED",
        2,
        f"Iniciando Dataset Harvester (teto rígido: {clamped_bytes // (1024 * 1024)} MB)...",
    )

    try:
        cfg = HarvesterConfig(
            max_bytes=clamped_bytes,
            enabled_sources=sources or ["wikimedia", "huggingface", "public_yolo", "cad_symbols"],
            max_items_per_source=max_items_per_source,
        )
        pipeline = DatasetHarvesterPipeline(
            config=cfg,
            progress_callback=lambda pct, msg: publish_job_event(job_id, "PROGRESS", pct, msg),
        )
        summary = pipeline.run(max_items_per_source=max_items_per_source)
        result_payload = {
            "output_dir": str(summary.output_dir),
            "manifest_path": str(summary.manifest_path),
            "dataset_yaml_path": str(summary.dataset_yaml_path),
            "quota_reached": summary.quota_reached,
            "used_bytes": summary.used_bytes,
            "max_bytes": summary.max_bytes,
            "labeled_counts": summary.labeled_counts,
            "unlabeled_count": summary.unlabeled_count,
            "cad_symbols_count": summary.cad_symbols_count,
            "counts_by_source": summary.counts_by_source,
            "counts_by_class": summary.counts_by_class,
        }
        publish_job_event(job_id, "COMPLETED", 100, "Dataset Harvester finalizado.", result_payload)
        return result_payload
    except Exception as exc:
        logger.exception("dataset_harvest_failed", error=str(exc))
        publish_job_event(job_id, "FAILED", 100, f"Erro no Dataset Harvester: {exc}")
        raise
