"""Automated tests for the Public Electrical Dataset Harvester (1 GB Hard Quota)."""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
import yaml
from httpx import AsyncClient
from PIL import Image

from app.core.celery_app import celery_app
from app.services.ml_ops.harvester.config import HARD_QUOTA_BYTES, HarvesterConfig
from app.services.ml_ops.harvester.pipeline import DatasetHarvesterPipeline
from app.services.ml_ops.harvester.processor import (
    ImageQualityProcessor,
    ImageRejectedError,
    TaxonomyMapper,
    YoloAnnotation,
)
from app.services.ml_ops.harvester.quota_manager import DiskQuotaManager, QuotaExceededError
from app.services.ml_ops.harvester.sources.base import (
    BaseSourceConnector,
    HarvestedItem,
    is_open_license,
)
from app.services.ml_ops.harvester.sources.public_yolo import (
    PublicYoloRepoConnector,
    PublicYoloSourceEntry,
)

TAXONOMY_FILE = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "ml_ops"
    / "harvester"
    / "taxonomy.yaml"
)


def _make_sharp_image_bytes(
    width: int = 800,
    height: int = 600,
    seed: int = 1,
    pattern: str = "checker",
) -> bytes:
    """Create a distinct, high-frequency sharp synthetic image guaranteed to pass blur > 50."""
    rng = np.random.default_rng(seed)
    img = np.zeros((height, width, 3), dtype=np.uint8)
    if pattern == "checker":
        step = 16 + (seed % 5) * 4
        for y in range(0, height, step):
            for x in range(0, width, step):
                if ((x // step) + (y // step)) % 2 == 0:
                    img[y : y + step, x : x + step] = rng.integers(140, 255, size=3)
                else:
                    img[y : y + step, x : x + step] = rng.integers(0, 80, size=3)
    elif pattern == "stripes":
        for x in range(0, width, 12):
            color = rng.integers(0, 255, size=3)
            img[:, x : x + 6] = color
        cv2.circle(img, (width // 2, height // 2), min(width, height) // 4, (255, 255, 255), 8)
    else:
        # Distinct random textured blocks
        for _ in range(80):
            x1 = int(rng.integers(0, width - 40))
            y1 = int(rng.integers(0, height - 40))
            w = int(rng.integers(20, 120))
            h = int(rng.integers(20, 120))
            col = tuple(int(c) for c in rng.integers(0, 255, size=3))
            cv2.rectangle(img, (x1, y1), (min(width - 1, x1 + w), min(height - 1, y1 + h)), col, -1)
            cv2.rectangle(img, (x1, y1), (min(width - 1, x1 + w), min(height - 1, y1 + h)), (255, 255, 255), 2)

    pil = Image.fromarray(img)
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


def _make_blurry_image_bytes(width: int = 640, height: int = 480) -> bytes:
    """Create a smooth low-gradient blurry image (Laplacian variance << 50)."""
    img = np.full((height, width, 3), 128, dtype=np.uint8)
    cv2.circle(img, (width // 2, height // 2), 80, (140, 140, 140), -1)
    blurred = cv2.GaussianBlur(img, (51, 51), 25)
    buf = io.BytesIO()
    Image.fromarray(blurred).save(buf, format="PNG")
    return buf.getvalue()


class _FakeConnector(BaseSourceConnector):
    def __init__(
        self,
        config: HarvesterConfig,
        taxonomy: TaxonomyMapper,
        source_name: str,
        items: list[HarvestedItem],
    ) -> None:
        super().__init__(config, taxonomy)
        self.source_name = source_name
        self._items = items

    def iter_items(self, limit: int | None = None) -> Iterator[HarvestedItem]:
        for count, item in enumerate(self._items):
            if limit is not None and count >= limit:
                break
            yield item


def test_quota_manager_enforces_exact_byte_cap_and_rejects_overflow(tmp_path: Path) -> None:
    # Cannot exceed global 950 MB hard cap
    with pytest.raises(ValueError):
        DiskQuotaManager(tmp_path / "bad", max_bytes=HARD_QUOTA_BYTES + 1)

    qm = DiskQuotaManager(tmp_path / "harvest", max_bytes=1024)
    qm.write_bytes(tmp_path / "harvest" / "a.bin", b"x" * 600)
    assert qm.used_bytes == 600
    assert qm.remaining_bytes == 424

    # Writing 425 bytes MUST raise QuotaExceededError without writing file
    with pytest.raises(QuotaExceededError):
        qm.write_bytes(tmp_path / "harvest" / "overflow.bin", b"y" * 425)
    assert not (tmp_path / "harvest" / "overflow.bin").exists()
    assert qm.used_bytes == 600

    # Exact remaining 424 bytes succeeds
    qm.write_bytes(tmp_path / "harvest" / "exact.bin", b"z" * 424)
    assert qm.used_bytes == 1024
    assert qm.is_exhausted is True


def test_processor_rejects_blurry_small_corrupted_and_deduplicates_phash(tmp_path: Path) -> None:
    cfg = HarvesterConfig(output_dir=tmp_path / "out", blur_threshold=50.0, phash_hamming_threshold=5)
    proc = ImageQualityProcessor(cfg)

    # 1. Corrupted payload rejected
    with pytest.raises(ImageRejectedError) as exc_corr:
        proc.process_bytes(b"not-an-image-payload-at-all")
    assert exc_corr.value.reason == "invalid_magic"

    # 2. Small image (< 320px) rejected
    small_bytes = _make_sharp_image_bytes(width=200, height=200, seed=10)
    with pytest.raises(ImageRejectedError) as exc_small:
        proc.process_bytes(small_bytes)
    assert exc_small.value.reason == "too_small"

    # 3. Blurry image (Laplacian variance < 50.0) rejected
    blurry_bytes = _make_blurry_image_bytes(640, 480)
    with pytest.raises(ImageRejectedError) as exc_blur:
        proc.process_bytes(blurry_bytes)
    assert exc_blur.value.reason == "blurry"

    # 4. Large 4K-like sharp image resized to <= 1280px preserving aspect ratio
    sharp_large = _make_sharp_image_bytes(width=2000, height=1000, seed=7, pattern="blocks")
    res1 = proc.process_bytes(sharp_large)
    assert res1.width == 1280
    assert res1.height == 640
    assert res1.blur_score >= 50.0

    # 5. Perceptual duplicate (same image with tiny brightness tweak -> Hamming <= 5) rejected
    with Image.open(io.BytesIO(sharp_large)) as im:
        arr = np.clip(np.asarray(im, dtype=np.int16) + 3, 0, 255).astype(np.uint8)
        dup_buf = io.BytesIO()
        Image.fromarray(arr).save(dup_buf, format="JPEG", quality=80)
    with pytest.raises(ImageRejectedError) as exc_dup:
        proc.process_bytes(dup_buf.getvalue())
    assert exc_dup.value.reason == "duplicate_phash"

    # 6. Distinct sharp image accepted
    distinct = _make_sharp_image_bytes(width=800, height=600, seed=99, pattern="stripes")
    res2 = proc.process_bytes(distinct)
    assert res2.sha256 != res1.sha256


def test_taxonomy_mapper_and_in_memory_public_yolo_remapping(tmp_path: Path) -> None:
    mapper = TaxonomyMapper(TAXONOMY_FILE)
    assert mapper.map_label("Quadro de Distribuição") == 0
    assert mapper.map_label("MCB 1P") == 1
    assert mapper.map_label("Disjuntor Bipolar") == 2
    assert mapper.map_label("MCCB") == 3
    assert mapper.map_label("Interruptor Diferencial Residual") == 4
    assert mapper.map_label("Protetor de Surto") == 5
    assert mapper.map_label("Barramento Pente") == 6
    assert mapper.map_label("Fiação") == 7
    assert mapper.map_label("Trafo") == 8
    assert mapper.map_label("Etiqueta") == 9
    assert mapper.map_label("unrelated_dog_class") is None

    # Build a synthetic YOLO ZIP archive strictly in memory
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr(
            "dataset/data.yaml",
            yaml.safe_dump({"names": ["RCD", "SPD", "unrelated_cat"]}),
        )
        zf.writestr("dataset/images/sample1.png", _make_sharp_image_bytes(seed=42, pattern="blocks"))
        zf.writestr(
            "dataset/labels/sample1.txt",
            "0 0.5 0.5 0.2 0.3\n1 0.2 0.3 0.1 0.2\n2 0.8 0.8 0.1 0.1\n",
        )

    cfg = HarvesterConfig(output_dir=tmp_path / "out")
    connector = PublicYoloRepoConnector(cfg, mapper, entries=[])
    entry = PublicYoloSourceEntry(
        name="synthetic_yolo",
        archive_url="https://example.org/open_yolo.zip",
        license="CC-BY-4.0",
    )
    items = list(connector.iter_from_zip_bytes(zip_buf.getvalue(), entry))
    assert len(items) == 1
    assert items[0].annotations is not None
    # Class 0 (RCD -> 4 idr_rcd), Class 1 (SPD -> 5 dps_spd), Class 2 (unrelated -> dropped)
    assert [a.class_id for a in items[0].annotations] == [4, 5]


def test_pipeline_graceful_quota_shutdown_stratified_split_and_manifest(tmp_path: Path) -> None:
    taxonomy = TaxonomyMapper(TAXONOMY_FILE)
    assert is_open_license("CC-BY-SA 4.0") is True
    assert is_open_license("CC-BY-NC 4.0") is False

    # Prepare 10 distinct labeled images + 2 unlabeled + 1 CAD SVG + 1 blurry + 1 non-open license
    labeled_items: list[HarvestedItem] = []
    for i in range(10):
        img_bytes = _make_sharp_image_bytes(width=700, height=500, seed=100 + i * 17, pattern="blocks")
        cid = 4 if i < 5 else 5  # 5 idr_rcd + 5 dps_spd for stratified split check
        labeled_items.append(
            HarvestedItem(
                item_id=f"lbl_{i}",
                source_name="public_yolo",
                source_url=f"https://example.org/item/{i}",
                license="MIT",
                media_kind="image",
                raw_bytes=img_bytes,
                filename=f"lbl_{i}.png",
                annotations=[YoloAnnotation(class_id=cid, cx=0.5, cy=0.5, w=0.25, h=0.35)],
            )
        )

    unlabeled_items = [
        HarvestedItem(
            item_id="wiki_1",
            source_name="wikimedia",
            source_url="https://commons.wikimedia.org/wiki/File:Panel1.jpg",
            license="CC-BY-4.0",
            media_kind="image",
            raw_bytes=_make_sharp_image_bytes(width=800, height=600, seed=501, pattern="stripes"),
            filename="panel1.png",
            annotations=None,
        ),
        HarvestedItem(
            item_id="wiki_blur",
            source_name="wikimedia",
            source_url="https://commons.wikimedia.org/wiki/File:Blur.jpg",
            license="CC0",
            media_kind="image",
            raw_bytes=_make_blurry_image_bytes(),
            filename="blur.png",
            annotations=None,
        ),
        HarvestedItem(
            item_id="wiki_nc",
            source_name="wikimedia",
            source_url="https://example.org/nc.jpg",
            license="CC-BY-NC-4.0",
            media_kind="image",
            raw_bytes=_make_sharp_image_bytes(width=800, height=600, seed=502, pattern="blocks"),
            filename="nc.png",
            annotations=None,
        ),
    ]

    cad_items = [
        HarvestedItem(
            item_id="cad_1",
            source_name="cad_symbols",
            source_url="https://github.com/example/iec60617/breaker.svg",
            license="Apache-2.0",
            media_kind="cad_symbol",
            raw_bytes=b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>',
            filename="iec_breaker.svg",
            annotations=None,
        )
    ]

    # 1. Full run within generous quota: verifies 70/15/15 stratified split + unlabeled + cad + manifest
    cfg_full = HarvesterConfig(output_dir=tmp_path / "full_harvest", max_bytes=10 * 1024 * 1024)
    pipeline_full = DatasetHarvesterPipeline(
        config=cfg_full,
        connectors=[
            _FakeConnector(cfg_full, taxonomy, "public_yolo", labeled_items),
            _FakeConnector(cfg_full, taxonomy, "wikimedia", unlabeled_items),
            _FakeConnector(cfg_full, taxonomy, "cad_symbols", cad_items),
        ],
    )
    summary = pipeline_full.run()
    assert summary.quota_reached is False
    assert summary.labeled_counts["train"] >= 6
    assert summary.labeled_counts["val"] >= 2
    assert summary.labeled_counts["golden_test"] >= 2
    assert sum(summary.labeled_counts.values()) == 10
    assert summary.unlabeled_count == 1
    assert summary.cad_symbols_count == 1
    assert summary.rejected_counts["blurry"] == 1
    assert summary.rejected_counts["non_open_license"] == 1
    assert summary.dataset_yaml_path.exists()
    assert summary.manifest_path.exists()

    manifest_data = json.loads(summary.manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["used_bytes"] <= cfg_full.max_bytes
    assert all("source_url" in s and "license" in s and "sha256" in s for s in manifest_data["samples"])

    # 2. Tight quota run (1 MB with 120 KB-ish synthetic images -> force graceful stop via low DiskQuotaManager)
    cfg_tight = HarvesterConfig(output_dir=tmp_path / "tight_harvest", max_bytes=1_048_576)
    pipeline_tight = DatasetHarvesterPipeline(
        config=cfg_tight,
        connectors=[_FakeConnector(cfg_tight, taxonomy, "public_yolo", labeled_items)],
    )
    # Force an ultra-tight cap (40 KB) directly on quota manager to test exact graceful shutdown
    pipeline_tight.quota = DiskQuotaManager(tmp_path / "tight_harvest", max_bytes=40_000)
    tight_summary = pipeline_tight.run()
    assert tight_summary.quota_reached is True
    assert tight_summary.used_bytes <= 40_000
    assert tight_summary.manifest_path.exists()
    assert tight_summary.dataset_yaml_path.exists()


async def test_harvest_start_api_endpoint(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exceeding 950 MB hard cap must fail validation with 422
    bad = await api_client.post(
        "/api/v1/ml/harvest/start",
        json={"max_mb": 1024},
    )
    assert bad.status_code == 422

    # Valid dispatch queues onto train_queue and returns SSE URL
    monkeypatch.setattr(
        celery_app,
        "send_task",
        lambda *_args, **_kwargs: SimpleNamespace(id="harvest-job-123"),
    )
    ok = await api_client.post(
        "/api/v1/ml/harvest/start",
        json={"max_mb": 20, "sources": ["wikimedia", "cad_symbols"], "max_items_per_source": 10},
    )
    assert ok.status_code == 202
    body = ok.json()
    assert body["job_id"] == "harvest-job-123"
    assert body["queue"] == "train_queue"
    assert body["sse_url"] == "/api/v1/events/jobs/harvest-job-123"
