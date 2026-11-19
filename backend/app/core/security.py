"""AppSec media validation: magic bytes, size limits, decompression bombs, path sanitization, SHA-256."""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from app.core.config import Settings, get_settings
from app.core.storage import ensure_within_base


class MediaSecurityError(ValueError):
    """Raised when an uploaded file fails security inspection."""


class MediaCategory(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    DXF = "dxf"
    PDF = "pdf"


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    """Result of successful AppSec upload inspection."""

    category: MediaCategory
    detected_mime: str
    extension: str
    sanitized_filename: str
    size_bytes: int
    sha256: str
    image_width: int | None = None
    image_height: int | None = None


_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_ALLOWED_EXTENSIONS: dict[MediaCategory, set[str]] = {
    MediaCategory.IMAGE: {".jpg", ".jpeg", ".png", ".webp"},
    MediaCategory.VIDEO: {".mp4", ".mov", ".avi", ".mkv"},
    MediaCategory.DXF: {".dxf"},
    MediaCategory.PDF: {".pdf"},
}


def sanitize_filename(original_name: str, fallback_stem: str = "upload") -> str:
    """Sanitize an untrusted filename, stripping directories, null bytes, and dangerous chars."""
    if "\x00" in original_name:
        raise MediaSecurityError("Null byte detected in filename.")

    # Normalize Windows/POSIX separators and take basename only
    basename = original_name.replace("\\", "/").split("/")[-1].strip()
    if not basename or basename in {".", ".."}:
        raise MediaSecurityError("Invalid or empty filename.")

    stem = Path(basename).stem
    suffix = Path(basename).suffix.lower()

    clean_stem = _SAFE_FILENAME_RE.sub("_", stem).strip("._-")
    if not clean_stem:
        clean_stem = fallback_stem
    clean_stem = clean_stem[:96]

    clean_suffix = _SAFE_FILENAME_RE.sub("", suffix)
    return f"{clean_stem}{clean_suffix}"


def detect_magic_mime(header: bytes) -> tuple[MediaCategory, str]:
    """Identify media category and MIME type strictly from magic bytes (never from extension)."""
    if len(header) < 4:
        raise MediaSecurityError("File too small to contain valid magic bytes.")

    # Images
    if header.startswith(b"\xff\xd8\xff"):
        return MediaCategory.IMAGE, "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return MediaCategory.IMAGE, "image/png"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return MediaCategory.IMAGE, "image/webp"

    # PDF
    if header.startswith(b"%PDF-"):
        return MediaCategory.PDF, "application/pdf"

    # Videos: ISO BMFF (MP4 / MOV), AVI, MKV
    if len(header) >= 12 and header[4:8] == b"ftyp":
        brand = header[8:12]
        if brand == b"qt  ":
            return MediaCategory.VIDEO, "video/quicktime"
        return MediaCategory.VIDEO, "video/mp4"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"AVI ":
        return MediaCategory.VIDEO, "video/x-msvideo"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return MediaCategory.VIDEO, "video/x-matroska"

    # DXF: Binary DXF sentinel or ASCII DXF group code structure
    if header.startswith(b"AutoCAD Binary DXF\r\n\x1a\x00"):
        return MediaCategory.DXF, "application/dxf"

    # ASCII DXF typically starts with group code 0 or 999 followed by SECTION / comment
    try:
        snippet = header[:512].decode("ascii", errors="strict")
    except UnicodeDecodeError:
        snippet = ""

    if snippet:
        lines = [line.strip() for line in snippet.splitlines() if line.strip()]
        if len(lines) >= 2 and lines[0] in {"0", "999"}:
            upper_joined = "\n".join(lines[:10]).upper()
            if "SECTION" in upper_joined or "HEADER" in upper_joined or "ENTITIES" in upper_joined:
                return MediaCategory.DXF, "application/dxf"

    raise MediaSecurityError("Unrecognized or unsupported file magic bytes.")


def _max_bytes_for_category(category: MediaCategory, settings: Settings) -> int:
    mb_map = {
        MediaCategory.IMAGE: settings.max_image_upload_mb,
        MediaCategory.VIDEO: settings.max_video_upload_mb,
        MediaCategory.DXF: settings.max_dxf_upload_mb,
        MediaCategory.PDF: settings.max_pdf_upload_mb,
    }
    return mb_map[category] * 1024 * 1024


def validate_upload_bytes(
    data: bytes,
    original_filename: str,
    expected_categories: set[MediaCategory] | None = None,
    settings: Settings | None = None,
) -> ValidatedUpload:
    """Validate uploaded bytes against magic bytes, size limits, and decompression bombs."""
    cfg = settings or get_settings()
    if not data:
        raise MediaSecurityError("Uploaded file is empty.")

    sanitized = sanitize_filename(original_filename)
    extension = Path(sanitized).suffix.lower()

    category, detected_mime = detect_magic_mime(data[:1024])

    if expected_categories is not None and category not in expected_categories:
        allowed = ", ".join(sorted(c.value for c in expected_categories))
        raise MediaSecurityError(
            f"Detected media category '{category.value}' is not allowed here (expected: {allowed})."
        )

    if extension not in _ALLOWED_EXTENSIONS[category]:
        raise MediaSecurityError(
            f"Filename extension '{extension}' does not match detected content '{detected_mime}'."
        )

    max_bytes = _max_bytes_for_category(category, cfg)
    size_bytes = len(data)
    if size_bytes > max_bytes:
        raise MediaSecurityError(
            f"File size ({size_bytes} bytes) exceeds maximum allowed ({max_bytes} bytes) "
            f"for category '{category.value}'."
        )

    width: int | None = None
    height: int | None = None

    if category == MediaCategory.IMAGE:
        width, height = _verify_image_no_bomb(data, max_pixels=cfg.max_image_pixels)

    digest = compute_sha256_bytes(data)

    return ValidatedUpload(
        category=category,
        detected_mime=detected_mime,
        extension=extension,
        sanitized_filename=sanitized,
        size_bytes=size_bytes,
        sha256=digest,
        image_width=width,
        image_height=height,
    )


def _verify_image_no_bomb(data: bytes, max_pixels: int) -> tuple[int, int]:
    """Inspect image dimensions and verify integrity while blocking decompression bombs."""
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            if width <= 0 or height <= 0:
                raise MediaSecurityError("Image has invalid non-positive dimensions.")
            if width * height > max_pixels:
                raise MediaSecurityError(
                    f"Image pixel count ({width * height}) exceeds decompression bomb limit "
                    f"({max_pixels})."
                )
            img.verify()
        return width, height
    except Image.DecompressionBombError as exc:
        raise MediaSecurityError(f"Decompression bomb detected: {exc}") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise MediaSecurityError(f"Corrupted or invalid image payload: {exc}") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit


def safe_storage_destination(base_dir: Path, *relative_parts: str) -> Path:
    """Build a storage path from relative parts and verify strict containment in base_dir."""
    if not relative_parts:
        raise MediaSecurityError("At least one relative path segment is required.")
    candidate = base_dir.joinpath(*relative_parts)
    return ensure_within_base(base_dir, candidate)


def compute_sha256_bytes(data: bytes) -> str:
    """Compute hexadecimal SHA-256 digest of bytes."""
    return hashlib.sha256(data).hexdigest()


def compute_sha256_file(path: Path, chunk_size: int = 65_536) -> str:
    """Stream-compute hexadecimal SHA-256 digest of a file on disk."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_canonical_json_sha256(payload: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash over canonical JSON (sorted keys, compact UTF-8)."""
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return compute_sha256_bytes(canonical)
