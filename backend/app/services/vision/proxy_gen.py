"""Lightweight image proxy & thumbnail generator (Pillow-only, runs safely inside api & worker-ml)."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from app.core.config import get_settings
from app.core.storage import atomic_write_bytes


@dataclass(frozen=True, slots=True)
class ProxyArtifacts:
    """Paths and dimensions of generated web proxy and thumbnail."""

    proxy_path: Path
    thumbnail_path: Path
    proxy_width: int
    proxy_height: int
    thumb_width: int
    thumb_height: int


def generate_image_proxies(
    source_image_path: Path,
    output_dir: Path,
    stem: str,
    proxy_max_dim: int = 1600,
    thumb_max_dim: int = 400,
    jpeg_quality: int = 85,
    base_dir: Path | None = None,
) -> ProxyArtifacts:
    """Generate EXIF-normalized web proxy and thumbnail with atomic writes."""
    settings = get_settings()
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
    try:
        with Image.open(source_image_path) as raw_img:
            normalized = ImageOps.exif_transpose(raw_img)
            rgb_img = normalized.convert("RGB")

            proxy_img = rgb_img.copy()
            proxy_img.thumbnail((proxy_max_dim, proxy_max_dim), Image.Resampling.LANCZOS)
            proxy_buf = io.BytesIO()
            proxy_img.save(proxy_buf, format="JPEG", quality=jpeg_quality, optimize=True)

            thumb_img = rgb_img.copy()
            thumb_img.thumbnail((thumb_max_dim, thumb_max_dim), Image.Resampling.LANCZOS)
            thumb_buf = io.BytesIO()
            thumb_img.save(thumb_buf, format="JPEG", quality=80, optimize=True)

            proxy_dest = output_dir / f"{stem}_proxy.jpg"
            thumb_dest = output_dir / f"{stem}_thumb.jpg"

            atomic_write_bytes(proxy_dest, proxy_buf.getvalue(), base_dir=base_dir)
            atomic_write_bytes(thumb_dest, thumb_buf.getvalue(), base_dir=base_dir)

            return ProxyArtifacts(
                proxy_path=proxy_dest,
                thumbnail_path=thumb_dest,
                proxy_width=proxy_img.width,
                proxy_height=proxy_img.height,
                thumb_width=thumb_img.width,
                thumb_height=thumb_img.height,
            )
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit
