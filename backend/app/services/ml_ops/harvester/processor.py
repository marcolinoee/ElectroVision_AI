"""In-memory image validation, blur filtering, pHash deduplication, resize (1280px JPEG 85) & taxonomy mapping."""

from __future__ import annotations

import hashlib
import io
import re
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import cv2
import imagehash
import numpy as np
import yaml
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.security import MediaCategory, MediaSecurityError, detect_magic_mime
from app.services.ml_ops.harvester.config import HarvesterConfig


class ImageRejectedError(ValueError):
    """Raised when an image fails quality, integrity, resolution, blur, or dedup gates."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class YoloAnnotation:
    """Single normalized YOLO bounding box mapped to unified ElectroVision class_id (0..9)."""

    class_id: int
    cx: float
    cy: float
    w: float
    h: float

    def to_yolo_line(self) -> str:
        return f"{self.class_id} {self.cx:.6f} {self.cy:.6f} {self.w:.6f} {self.h:.6f}"


@dataclass(frozen=True, slots=True)
class ProcessedImage:
    """Validated, deduplicated, resized JPEG payload ready for quota-controlled storage."""

    jpeg_bytes: bytes
    width: int
    height: int
    sha256: str
    phash_hex: str
    blur_score: float


def _normalize_label(raw: str) -> str:
    decomposed = unicodedata.normalize("NFKD", raw.strip().lower())
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    collapsed = re.sub(r"[^a-z0-9]+", " ", ascii_only).strip()
    return collapsed


class TaxonomyMapper:
    """Deterministic synonym mapper from heterogeneous public labels to unified classes 0..9."""

    def __init__(self, taxonomy_path: Path) -> None:
        data = yaml.safe_load(taxonomy_path.read_text(encoding="utf-8"))
        self.classes: dict[int, str] = {int(k): str(v) for k, v in data["classes"].items()}
        name_to_id = {name: cid for cid, name in self.classes.items()}

        self._synonym_to_id: dict[str, int] = {}
        for canonical_name, synonyms in data.get("synonyms", {}).items():
            cid = name_to_id[canonical_name]
            self._synonym_to_id[_normalize_label(canonical_name)] = cid
            for syn in synonyms:
                self._synonym_to_id[_normalize_label(str(syn))] = cid

    def map_label(self, raw_label: str) -> int | None:
        """Map an external class name to unified class_id (0..9) or None if unmapped."""
        norm = _normalize_label(raw_label)
        if not norm:
            return None
        if norm in self._synonym_to_id:
            return self._synonym_to_id[norm]
        # Substring fallback for composite labels (e.g. "siemens_mcb_2p_20a")
        for syn, cid in self._synonym_to_id.items():
            if len(syn) >= 4 and syn in norm:
                return cid
        return None

    def remap_yolo_lines(
        self,
        yolo_text: str,
        source_class_names: dict[int, str],
    ) -> list[YoloAnnotation]:
        """Remap raw YOLO `.txt` annotation lines using `source_class_names` -> unified 0..9."""
        mapped: list[YoloAnnotation] = []
        for raw_line in yolo_text.splitlines():
            parts = raw_line.strip().split()
            if len(parts) < 5:
                continue
            try:
                src_cid = int(float(parts[0]))
                cx, cy, w, h = (float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]))
            except ValueError:
                continue
            src_name = source_class_names.get(src_cid)
            if not src_name:
                continue
            unified_id = self.map_label(src_name)
            if unified_id is None:
                continue
            if w <= 0.0 or h <= 0.0 or cx < 0.0 or cy < 0.0 or cx > 1.0 or cy > 1.0:
                continue
            mapped.append(
                YoloAnnotation(
                    class_id=unified_id,
                    cx=max(0.0, min(1.0, cx)),
                    cy=max(0.0, min(1.0, cy)),
                    w=max(1e-4, min(1.0, w)),
                    h=max(1e-4, min(1.0, h)),
                )
            )
        return mapped


class ImageQualityProcessor:
    """In-memory validator, blur filter, pHash deduplicator, and on-the-fly 1280px JPEG encoder."""

    def __init__(self, config: HarvesterConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._seen_phashes: list[imagehash.ImageHash] = []
        self._seen_sha256: set[str] = set()

    @property
    def seen_count(self) -> int:
        with self._lock:
            return len(self._seen_phashes)

    def process_bytes(self, raw_bytes: bytes) -> ProcessedImage:
        """Validate, filter blur/resolution, deduplicate by pHash, and re-encode <= 1280px JPEG."""
        if not raw_bytes or len(raw_bytes) < 16:
            raise ImageRejectedError("corrupted", "Payload empty or too small.")

        # 1. Magic bytes validation (JPEG/PNG/WEBP)
        try:
            category, _mime = detect_magic_mime(raw_bytes[:64])
            if category != MediaCategory.IMAGE:
                raise ImageRejectedError("invalid_magic", f"Expected image, got {category.value}.")
        except MediaSecurityError as exc:
            raise ImageRejectedError("invalid_magic", str(exc)) from exc

        # 2. Decode safely in memory with decompression bomb protection
        prev_limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = 40_000_000
        try:
            with Image.open(io.BytesIO(raw_bytes)) as img:
                img.load()
                normalized = ImageOps.exif_transpose(img).convert("RGB")
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
            raise ImageRejectedError("corrupted", f"Failed to decode image: {exc}") from exc
        finally:
            Image.MAX_IMAGE_PIXELS = prev_limit

        orig_w, orig_h = normalized.size
        if orig_w < self._config.min_width or orig_h < self._config.min_height:
            raise ImageRejectedError(
                "too_small",
                f"Resolution {orig_w}x{orig_h} below minimum {self._config.min_width}x{self._config.min_height}.",
            )

        # 3. Resize longest side to <= max_dimension (1280px) preserving aspect ratio
        if max(orig_w, orig_h) > self._config.max_dimension:
            normalized.thumbnail(
                (self._config.max_dimension, self._config.max_dimension),
                Image.Resampling.LANCZOS,
            )

        # 4. Blur filter via OpenCV Laplacian variance
        rgb_arr = np.asarray(normalized)
        gray = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2GRAY)
        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if blur_score < self._config.blur_threshold:
            raise ImageRejectedError(
                "blurry",
                f"Laplacian variance {blur_score:.2f} < threshold {self._config.blur_threshold:.2f}.",
            )

        # 5. Perceptual deduplication via pHash (Hamming distance <= 5)
        phash_val = imagehash.phash(normalized)
        with self._lock:
            for existing_hash in self._seen_phashes:
                dist = int(phash_val - existing_hash)
                if dist <= self._config.phash_hamming_threshold:
                    raise ImageRejectedError(
                        "duplicate_phash",
                        f"Perceptual duplicate detected (Hamming={dist} <= "
                        f"{self._config.phash_hamming_threshold}).",
                    )

            # 6. Encode optimized JPEG (quality 85) in memory
            out_buf = io.BytesIO()
            normalized.save(
                out_buf,
                format="JPEG",
                quality=self._config.jpeg_quality,
                optimize=True,
            )
            jpeg_bytes = out_buf.getvalue()
            sha256_hex = hashlib.sha256(jpeg_bytes).hexdigest()
            if sha256_hex in self._seen_sha256:
                raise ImageRejectedError("duplicate_sha256", "Exact SHA-256 duplicate.")

            self._seen_phashes.append(phash_val)
            self._seen_sha256.add(sha256_hex)

        final_w, final_h = normalized.size
        return ProcessedImage(
            jpeg_bytes=jpeg_bytes,
            width=final_w,
            height=final_h,
            sha256=sha256_hex,
            phash_hex=str(phash_val),
            blur_score=round(blur_score, 2),
        )
