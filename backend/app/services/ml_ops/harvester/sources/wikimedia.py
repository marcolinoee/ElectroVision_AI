"""Wikimedia Commons API (`action=query`) open-license electrical imagery connector."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from typing import Any

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

WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"

DEFAULT_WIKIMEDIA_QUERIES: tuple[str, ...] = (
    "electrical distribution board",
    "circuit breaker panel",
    "quadro de distribuição elétrico",
    "switchgear",
    "electrical substation transformer",
    "DIN rail breaker",
)


class WikimediaCommonsConnector(BaseSourceConnector):
    """Streams CC/PD high-res electrical panel & switchgear photos via Wikimedia Commons API."""

    source_name = "wikimedia"

    def __init__(
        self,
        config: HarvesterConfig,
        taxonomy: TaxonomyMapper,
        queries: tuple[str, ...] = DEFAULT_WIKIMEDIA_QUERIES,
    ) -> None:
        super().__init__(config, taxonomy)
        self._queries = queries

    def iter_items(self, limit: int | None = None) -> Iterator[HarvestedItem]:
        max_total = limit or self.config.max_items_per_source
        yielded = 0
        seen_urls: set[str] = set()

        with self._build_http_client() as client:
            for query in self._queries:
                if yielded >= max_total:
                    break
                gsr_offset: int | None = 0
                while gsr_offset is not None and yielded < max_total:
                    params: dict[str, Any] = {
                        "action": "query",
                        "format": "json",
                        "generator": "search",
                        "gsrnamespace": 6,  # File namespace
                        "gsrsearch": f"filetype:bitmap {query}",
                        "gsrlimit": 25,
                        "gsroffset": gsr_offset,
                        "prop": "imageinfo",
                        "iiprop": "url|size|mime|extmetadata",
                    }
                    try:
                        resp = http_get_with_backoff(
                            client,
                            WIKIMEDIA_API_URL,
                            params=params,
                            max_retries=self.config.max_retries,
                            backoff_base_s=self.config.backoff_base_s,
                        )
                        payload = resp.json()
                    except Exception as exc:
                        logger.warning("wikimedia_query_failed", query=query, error=str(exc))
                        break

                    pages = payload.get("query", {}).get("pages", {})
                    if not pages:
                        break

                    for page in pages.values():
                        if yielded >= max_total:
                            break
                        infos = page.get("imageinfo") or []
                        if not infos:
                            continue
                        info = infos[0]
                        mime = str(info.get("mime", "")).lower()
                        if mime not in {"image/jpeg", "image/png", "image/webp"}:
                            continue

                        width = int(info.get("width", 0))
                        height = int(info.get("height", 0))
                        if (
                            width < self.config.wikimedia_min_width
                            or height < self.config.wikimedia_min_height
                        ):
                            continue

                        extmeta = info.get("extmetadata", {})
                        license_name = str(
                            extmeta.get("LicenseShortName", {}).get("value")
                            or extmeta.get("License", {}).get("value")
                            or ""
                        ).strip()
                        if not is_open_license(license_name):
                            continue

                        img_url = str(info.get("url", ""))
                        if not img_url or img_url in seen_urls:
                            continue
                        seen_urls.add(img_url)

                        try:
                            img_resp = http_get_with_backoff(
                                client,
                                img_url,
                                max_retries=self.config.max_retries,
                                backoff_base_s=self.config.backoff_base_s,
                            )
                            raw_bytes = img_resp.content
                        except Exception as exc:
                            logger.warning("wikimedia_download_failed", url=img_url, error=str(exc))
                            continue

                        item_id = hashlib.sha1(img_url.encode("utf-8")).hexdigest()[:16]
                        title = str(page.get("title", f"wiki_{item_id}.jpg")).replace("File:", "")
                        yield HarvestedItem(
                            item_id=f"wiki_{item_id}",
                            source_name=self.source_name,
                            source_url=img_url,
                            license=license_name,
                            media_kind="image",
                            raw_bytes=raw_bytes,
                            filename=title,
                            annotations=None,  # Unlabeled -> routed to unlabeled/
                            metadata={"query": query, "orig_width": width, "orig_height": height},
                        )
                        yielded += 1

                    cont = payload.get("continue", {})
                    gsr_offset = cont.get("gsroffset")
