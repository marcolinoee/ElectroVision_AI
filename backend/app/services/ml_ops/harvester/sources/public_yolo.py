"""Public YOLO / Roboflow Universe / GitHub archive connector (100% in-memory ZIP streaming)."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.core.logging import get_logger
from app.services.ml_ops.harvester.config import HarvesterConfig
from app.services.ml_ops.harvester.processor import TaxonomyMapper
from app.services.ml_ops.harvester.sources.base import (
    BaseSourceConnector,
    HarvestedItem,
    http_get_with_backoff,
    is_open_license,
)

logger = get_logger(__name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True, slots=True)
class PublicYoloSourceEntry:
    """Configurable public YOLO repository or open-license ZIP archive."""

    name: str
    archive_url: str
    license: str
    class_names_override: dict[int, str] | None = None


def load_public_yolo_manifest(manifest_path: Path | None) -> list[PublicYoloSourceEntry]:
    """Load configurable YAML/JSON list of public YOLO archives."""
    if manifest_path is None or not manifest_path.exists():
        return []
    raw = manifest_path.read_text(encoding="utf-8")
    parsed: Any = (
        json.loads(raw) if manifest_path.suffix.lower() == ".json" else yaml.safe_load(raw)
    )
    entries: list[PublicYoloSourceEntry] = []
    for item in parsed or []:
        override = item.get("class_names")
        parsed_override = (
            {int(k): str(v) for k, v in override.items()} if isinstance(override, dict) else None
        )
        entries.append(
            PublicYoloSourceEntry(
                name=str(item["name"]),
                archive_url=str(item["archive_url"]),
                license=str(item["license"]),
                class_names_override=parsed_override,
            )
        )
    return entries


def _parse_data_yaml_names(zf: zipfile.ZipFile) -> dict[int, str]:
    for member in zf.namelist():
        if Path(member).name.lower() in {"data.yaml", "dataset.yaml"}:
            data = yaml.safe_load(zf.read(member).decode("utf-8", errors="ignore"))
            names = data.get("names") if isinstance(data, dict) else None
            if isinstance(names, list):
                return {idx: str(n) for idx, n in enumerate(names)}
            if isinstance(names, dict):
                return {int(k): str(v) for k, v in names.items()}
    return {}


class PublicYoloRepoConnector(BaseSourceConnector):
    """Ingests public YOLO ZIP archives in memory (never writes .zip to disk) and remaps classes."""

    source_name = "public_yolo"

    def __init__(
        self,
        config: HarvesterConfig,
        taxonomy: TaxonomyMapper,
        entries: list[PublicYoloSourceEntry] | None = None,
    ) -> None:
        super().__init__(config, taxonomy)
        self._entries = (
            entries
            if entries is not None
            else load_public_yolo_manifest(config.public_yolo_manifest_path)
        )

    def iter_from_zip_bytes(
        self,
        zip_bytes: bytes,
        entry: PublicYoloSourceEntry,
        limit: int | None = None,
    ) -> Iterator[HarvestedItem]:
        """Parse a YOLO archive strictly from an in-memory BytesIO buffer."""
        if not is_open_license(entry.license):
            logger.warning("public_yolo_skip_license", name=entry.name, license=entry.license)
            return

        yielded = 0
        with zipfile.ZipFile(io.BytesIO(zip_bytes), mode="r") as zf:
            source_names = entry.class_names_override or _parse_data_yaml_names(zf)
            all_members = zf.namelist()
            label_lookup: dict[str, str] = {
                Path(m).stem: m for m in all_members if m.lower().endswith(".txt")
            }

            for member in all_members:
                if limit is not None and yielded >= limit:
                    break
                p = Path(member)
                if p.suffix.lower() not in _IMAGE_EXTS or p.name.startswith("."):
                    continue

                raw_img = zf.read(member)
                annotations = None
                lbl_member = label_lookup.get(p.stem)
                if lbl_member and source_names:
                    lbl_text = zf.read(lbl_member).decode("utf-8", errors="ignore")
                    remapped = self.taxonomy.remap_yolo_lines(lbl_text, source_names)
                    if remapped:
                        annotations = remapped

                item_hash = hashlib.sha1(f"{entry.name}:{member}".encode()).hexdigest()[:16]
                yield HarvestedItem(
                    item_id=f"yolo_{item_hash}",
                    source_name=self.source_name,
                    source_url=entry.archive_url,
                    license=entry.license,
                    media_kind="image",
                    raw_bytes=raw_img,
                    filename=p.name,
                    annotations=annotations,
                    metadata={"archive_name": entry.name, "archive_member": member},
                )
                yielded += 1

    def iter_items(self, limit: int | None = None) -> Iterator[HarvestedItem]:
        if not self._entries:
            logger.info("public_yolo_no_entries_configured")
            return

        max_total = limit or self.config.max_items_per_source
        yielded = 0

        with self._build_http_client() as client:
            for entry in self._entries:
                if yielded >= max_total:
                    break
                if not is_open_license(entry.license):
                    continue
                try:
                    resp = http_get_with_backoff(
                        client,
                        entry.archive_url,
                        max_retries=self.config.max_retries,
                        backoff_base_s=self.config.backoff_base_s,
                    )
                    zip_bytes = resp.content
                except Exception as exc:
                    logger.warning(
                        "public_yolo_download_failed",
                        name=entry.name,
                        url=entry.archive_url,
                        error=str(exc),
                    )
                    continue

                remaining = max_total - yielded
                for item in self.iter_from_zip_bytes(zip_bytes, entry, limit=remaining):
                    yield item
                    yielded += 1
