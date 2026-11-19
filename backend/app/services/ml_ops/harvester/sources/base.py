"""Abstract BaseSourceConnector, HarvestedItem contract, open-license guard & exponential backoff HTTP."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from app.core.logging import get_logger
from app.services.ml_ops.harvester.config import HarvesterConfig
from app.services.ml_ops.harvester.processor import TaxonomyMapper, YoloAnnotation

logger = get_logger(__name__)

_ALLOWED_OPEN_LICENSE_MARKERS: tuple[str, ...] = (
    "cc0",
    "cc-0",
    "cc by",
    "cc-by",
    "cc-by-sa",
    "cc by-sa",
    "mit",
    "apache",
    "public domain",
    "pd-",
    "pd ",
    "unlicense",
    "bsd",
    "gpl",
    "lgpl",
    "mpl",
)

_FORBIDDEN_LICENSE_MARKERS: tuple[str, ...] = (
    "non-commercial",
    "nc-",
    "-nc",
    "all rights reserved",
    "proprietary",
    "fair use",
)


def is_open_license(license_str: str | None) -> bool:
    """Verify that a resource declares a permissive/open license (CC-BY, CC0, MIT, Apache, PD)."""
    if not license_str:
        return False
    norm = license_str.strip().lower()
    if any(bad in norm for bad in _FORBIDDEN_LICENSE_MARKERS):
        return False
    return any(good in norm for good in _ALLOWED_OPEN_LICENSE_MARKERS)


@dataclass(frozen=True, slots=True)
class HarvestedItem:
    """Single in-memory candidate item yielded by a source connector."""

    item_id: str
    source_name: str
    source_url: str
    license: str
    media_kind: Literal["image", "cad_symbol"]
    raw_bytes: bytes
    filename: str
    annotations: list[YoloAnnotation] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def http_get_with_backoff(
    client: httpx.Client,
    url: str,
    params: dict[str, Any] | None = None,
    max_retries: int = 4,
    backoff_base_s: float = 1.0,
) -> httpx.Response:
    """Perform an HTTP GET respecting rate limits (429/5xx) with exponential backoff."""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = client.get(url, params=params, follow_redirects=True)
            if response.status_code == 200:
                return response
            if response.status_code in {429, 500, 502, 503, 504}:
                retry_after = response.headers.get("Retry-After")
                delay = (
                    float(retry_after)
                    if retry_after and retry_after.isdigit()
                    else backoff_base_s * (2**attempt)
                )
                logger.warning(
                    "harvester_http_retry",
                    url=url,
                    status_code=response.status_code,
                    attempt=attempt + 1,
                    delay_s=delay,
                )
                time.sleep(min(delay, 30.0))
                continue
            response.raise_for_status()
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            delay = backoff_base_s * (2**attempt)
            logger.warning(
                "harvester_http_error",
                url=url,
                error=str(exc),
                attempt=attempt + 1,
                delay_s=delay,
            )
            if attempt + 1 < max_retries:
                time.sleep(min(delay, 30.0))
    raise RuntimeError(f"Failed HTTP GET after {max_retries} attempts for {url}: {last_exc}")


class BaseSourceConnector(ABC):
    """Abstract interface for all public electrical data connectors."""

    source_name: str = "base"

    def __init__(self, config: HarvesterConfig, taxonomy: TaxonomyMapper) -> None:
        self.config = config
        self.taxonomy = taxonomy

    def _build_http_client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.config.http_timeout_s,
            headers={"User-Agent": self.config.user_agent},
            follow_redirects=True,
        )

    @abstractmethod
    def iter_items(self, limit: int | None = None) -> Iterator[HarvestedItem]:
        """Stream candidate open-license items in memory without writing raw files to disk."""
        ...
