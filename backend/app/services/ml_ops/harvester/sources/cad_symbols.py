"""Public open-source CAD/Diagram electrical symbols connector (IEC 60617 / NBR 5444 .DXF & .SVG)."""

from __future__ import annotations

import hashlib
import json
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

_CAD_EXTS = {".dxf", ".svg"}


@dataclass(frozen=True, slots=True)
class CadSymbolRepoSpec:
    """Open-source GitHub repository containing IEC 60617 / NBR 5444 electrical symbols."""

    owner: str
    repo: str
    branch: str = "main"
    path_prefix: str = ""
    license: str = "MIT"


DEFAULT_CAD_REPOS: tuple[CadSymbolRepoSpec, ...] = (
    CadSymbolRepoSpec(
        owner="qelectrotech",
        repo="qelectrotech-source-mirror",
        branch="master",
        path_prefix="elements/10_electric/10_allpole",
        license="GPL-2.0",
    ),
)


def is_valid_cad_symbol_bytes(data: bytes, extension: str) -> bool:
    """Verify basic integrity of .SVG or .DXF symbol payloads in memory."""
    if not data or len(data) < 16:
        return False
    ext = extension.lower()
    if ext == ".svg":
        head = data[:512].decode("utf-8", errors="ignore").lower()
        return "<svg" in head
    if ext == ".dxf":
        if data.startswith(b"AutoCAD Binary DXF\r\n\x1a\x00"):
            return True
        head = data[:512].decode("ascii", errors="ignore").upper()
        return "SECTION" in head or "ENTITIES" in head
    return False


def load_cad_manifest(manifest_path: Path | None) -> list[CadSymbolRepoSpec]:
    if manifest_path is None or not manifest_path.exists():
        return list(DEFAULT_CAD_REPOS)
    raw = manifest_path.read_text(encoding="utf-8")
    parsed: Any = (
        json.loads(raw) if manifest_path.suffix.lower() == ".json" else yaml.safe_load(raw)
    )
    return [
        CadSymbolRepoSpec(
            owner=str(item["owner"]),
            repo=str(item["repo"]),
            branch=str(item.get("branch", "main")),
            path_prefix=str(item.get("path_prefix", "")),
            license=str(item.get("license", "MIT")),
        )
        for item in (parsed or [])
    ]


class CadSymbolsConnector(BaseSourceConnector):
    """Collects open-source .DXF and .SVG electrical symbols (IEC 60617 / NBR 5444)."""

    source_name = "cad_symbols"

    def __init__(
        self,
        config: HarvesterConfig,
        taxonomy: TaxonomyMapper,
        repos: list[CadSymbolRepoSpec] | None = None,
    ) -> None:
        super().__init__(config, taxonomy)
        self._repos = repos if repos is not None else load_cad_manifest(config.cad_symbols_manifest_path)

    def iter_items(self, limit: int | None = None) -> Iterator[HarvestedItem]:
        max_total = limit or min(300, self.config.max_items_per_source)
        yielded = 0

        with self._build_http_client() as client:
            for spec in self._repos:
                if yielded >= max_total:
                    break
                if not is_open_license(spec.license):
                    continue

                tree_url = f"https://api.github.com/repos/{spec.owner}/{spec.repo}/git/trees/{spec.branch}"
                try:
                    resp = http_get_with_backoff(
                        client,
                        tree_url,
                        params={"recursive": "1"},
                        max_retries=self.config.max_retries,
                        backoff_base_s=self.config.backoff_base_s,
                    )
                    tree = resp.json().get("tree", [])
                except Exception as exc:
                    logger.warning("cad_repo_tree_failed", repo=f"{spec.owner}/{spec.repo}", error=str(exc))
                    continue

                for node in tree:
                    if yielded >= max_total:
                        break
                    if node.get("type") != "blob":
                        continue
                    rel_path = str(node.get("path", ""))
                    if spec.path_prefix and not rel_path.startswith(spec.path_prefix):
                        continue
                    ext = Path(rel_path).suffix.lower()
                    if ext not in _CAD_EXTS:
                        continue

                    raw_url = f"https://raw.githubusercontent.com/{spec.owner}/{spec.repo}/{spec.branch}/{rel_path}"
                    try:
                        file_resp = http_get_with_backoff(
                            client,
                            raw_url,
                            max_retries=self.config.max_retries,
                            backoff_base_s=self.config.backoff_base_s,
                        )
                        content = file_resp.content
                    except Exception as exc:
                        logger.warning("cad_symbol_download_failed", url=raw_url, error=str(exc))
                        continue

                    if not is_valid_cad_symbol_bytes(content, ext):
                        continue

                    item_hash = hashlib.sha1(raw_url.encode("utf-8")).hexdigest()[:16]
                    yield HarvestedItem(
                        item_id=f"cad_{item_hash}",
                        source_name=self.source_name,
                        source_url=raw_url,
                        license=spec.license,
                        media_kind="cad_symbol",
                        raw_bytes=content,
                        filename=f"{item_hash}_{Path(rel_path).name}",
                        annotations=None,
                        metadata={"repo": f"{spec.owner}/{spec.repo}", "path": rel_path},
                    )
                    yielded += 1
