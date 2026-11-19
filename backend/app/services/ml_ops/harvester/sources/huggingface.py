"""Hugging Face Streaming (`streaming=True`) connector for public electrical/component datasets."""

from __future__ import annotations

import hashlib
import io
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from PIL import Image

from app.core.logging import get_logger
from app.services.ml_ops.harvester.config import HarvesterConfig
from app.services.ml_ops.harvester.processor import TaxonomyMapper, YoloAnnotation
from app.services.ml_ops.harvester.sources.base import (
    BaseSourceConnector,
    HarvestedItem,
    is_open_license,
)

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class HuggingFaceDatasetSpec:
    """Declarative specification for a public open-license Hugging Face dataset."""

    repo_id: str
    split: str = "train"
    license: str = "CC-BY-4.0"
    image_field: str = "image"
    objects_field: str = "objects"
    bbox_format: str = "coco"  # coco: [x, y, w, h] px | xyxy: [x1, y1, x2, y2] px
    label_names: dict[int, str] | None = None
    config_name: str | None = None


DEFAULT_HF_SPECS: tuple[HuggingFaceDatasetSpec, ...] = (
    HuggingFaceDatasetSpec(
        repo_id="keremberke/electrical-components-detection",
        split="train",
        license="MIT",
        bbox_format="coco",
    ),
    HuggingFaceDatasetSpec(
        repo_id="Francesco/electrical-symbols",
        split="train",
        license="CC-BY-4.0",
        bbox_format="coco",
    ),
)


class HuggingFaceStreamingConnector(BaseSourceConnector):
    """Streams Hugging Face datasets without downloading full archives to disk."""

    source_name = "huggingface"

    def __init__(
        self,
        config: HarvesterConfig,
        taxonomy: TaxonomyMapper,
        dataset_specs: tuple[HuggingFaceDatasetSpec, ...] = DEFAULT_HF_SPECS,
    ) -> None:
        super().__init__(config, taxonomy)
        self._specs = dataset_specs

    def _extract_annotations(
        self,
        row: dict[str, Any],
        spec: HuggingFaceDatasetSpec,
        img_w: int,
        img_h: int,
        feature_names: list[str] | None,
    ) -> list[YoloAnnotation]:
        objects = row.get(spec.objects_field)
        if not isinstance(objects, dict):
            return []

        bboxes = objects.get("bbox") or objects.get("bboxes") or []
        categories = objects.get("category") or objects.get("label") or objects.get("categories") or []
        results: list[YoloAnnotation] = []

        for bbox, cat in zip(bboxes, categories, strict=False):
            if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                continue
            if isinstance(cat, int):
                if spec.label_names and cat in spec.label_names:
                    raw_name = spec.label_names[cat]
                elif feature_names and 0 <= cat < len(feature_names):
                    raw_name = feature_names[cat]
                else:
                    continue
            else:
                raw_name = str(cat)

            unified_id = self.taxonomy.map_label(raw_name)
            if unified_id is None:
                continue

            b0, b1, b2, b3 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
            if spec.bbox_format == "xyxy":
                x1, y1, x2, y2 = b0, b1, b2, b3
                bw, bh = x2 - x1, y2 - y1
            else:
                x1, y1, bw, bh = b0, b1, b2, b3

            if bw <= 0 or bh <= 0 or img_w <= 0 or img_h <= 0:
                continue

            # Handle both pixel coordinates and already-normalized [0..1] coordinates
            if max(x1, y1, bw, bh) > 1.5:
                cx = (x1 + bw / 2.0) / img_w
                cy = (y1 + bh / 2.0) / img_h
                nw = bw / img_w
                nh = bh / img_h
            else:
                cx = x1 + bw / 2.0
                cy = y1 + bh / 2.0
                nw = bw
                nh = bh

            results.append(
                YoloAnnotation(
                    class_id=unified_id,
                    cx=max(0.0, min(1.0, cx)),
                    cy=max(0.0, min(1.0, cy)),
                    w=max(1e-4, min(1.0, nw)),
                    h=max(1e-4, min(1.0, nh)),
                )
            )
        return results

    def iter_items(self, limit: int | None = None) -> Iterator[HarvestedItem]:
        try:
            from datasets import load_dataset
        except ImportError:
            logger.warning("huggingface_datasets_not_installed")
            return

        max_total = limit or self.config.max_items_per_source
        yielded = 0

        for spec in self._specs:
            if yielded >= max_total:
                break
            if not is_open_license(spec.license):
                logger.warning("hf_skip_non_open_license", repo=spec.repo_id, license=spec.license)
                continue

            try:
                ds = load_dataset(
                    spec.repo_id,
                    name=spec.config_name,
                    split=spec.split,
                    streaming=True,
                )
            except Exception as exc:
                logger.warning("hf_dataset_unavailable", repo=spec.repo_id, error=str(exc))
                continue

            feature_names: list[str] | None = None
            features = getattr(ds, "features", None)
            if features and spec.objects_field in features:
                obj_feat = features[spec.objects_field]
                cat_feat = getattr(obj_feat, "feature", obj_feat)
                if isinstance(cat_feat, dict) and "category" in cat_feat:
                    feature_names = getattr(cat_feat["category"], "names", None)

            for idx, row in enumerate(ds):
                if yielded >= max_total:
                    break
                pil_img = row.get(spec.image_field)
                if not isinstance(pil_img, Image.Image):
                    continue

                rgb = pil_img.convert("RGB")
                buf = io.BytesIO()
                rgb.save(buf, format="JPEG", quality=92)
                raw_bytes = buf.getvalue()

                annotations = self._extract_annotations(
                    row=row,
                    spec=spec,
                    img_w=rgb.width,
                    img_h=rgb.height,
                    feature_names=feature_names,
                )
                item_hash = hashlib.sha1(f"{spec.repo_id}:{spec.split}:{idx}".encode()).hexdigest()[:16]
                yield HarvestedItem(
                    item_id=f"hf_{item_hash}",
                    source_name=self.source_name,
                    source_url=f"https://huggingface.co/datasets/{spec.repo_id}",
                    license=spec.license,
                    media_kind="image",
                    raw_bytes=raw_bytes,
                    filename=f"hf_{item_hash}.jpg",
                    annotations=annotations if annotations else None,
                    metadata={"repo_id": spec.repo_id, "split": spec.split, "row_index": idx},
                )
                yielded += 1
