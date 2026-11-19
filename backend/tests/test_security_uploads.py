"""AppSec tests: magic bytes, spoofed extensions, decompression bombs, path traversal, atomic writes."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import Settings
from app.core.security import (
    MediaCategory,
    MediaSecurityError,
    safe_storage_destination,
    sanitize_filename,
    validate_upload_bytes,
)
from app.core.storage import PathTraversalError, atomic_write_bytes


def _make_png_bytes(width: int = 32, height: int = 32) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=(20, 120, 220))
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_valid_png_upload_passes_magic_bytes_and_hashes() -> None:
    png = _make_png_bytes(64, 48)
    result = validate_upload_bytes(
        data=png,
        original_filename="quadro_eletrico_01.png",
        expected_categories={MediaCategory.IMAGE},
    )
    assert result.category == MediaCategory.IMAGE
    assert result.detected_mime == "image/png"
    assert result.image_width == 64
    assert result.image_height == 48
    assert len(result.sha256) == 64


def test_rejects_spoofed_extension_executable_as_jpg() -> None:
    fake_jpg = b"MZ\x90\x00\x03\x00\x00\x00This is a PE executable masquerading as jpg"
    with pytest.raises(MediaSecurityError, match="Unrecognized or unsupported"):
        validate_upload_bytes(
            data=fake_jpg,
            original_filename="panel.jpg",
            expected_categories={MediaCategory.IMAGE},
        )


def test_rejects_mismatched_extension_png_bytes_named_pdf() -> None:
    png = _make_png_bytes()
    with pytest.raises(MediaSecurityError, match="does not match detected content"):
        validate_upload_bytes(
            data=png,
            original_filename="norma.pdf",
        )


def test_accepts_valid_ascii_dxf_and_pdf_magic_bytes() -> None:
    dxf_bytes = b"  0\r\nSECTION\r\n  2\r\nHEADER\r\n  0\r\nENDSEC\r\n  0\r\nEOF\r\n"
    res_dxf = validate_upload_bytes(
        data=dxf_bytes,
        original_filename="planta_arquitetura.dxf",
        expected_categories={MediaCategory.DXF},
    )
    assert res_dxf.category == MediaCategory.DXF

    pdf_bytes = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"
    res_pdf = validate_upload_bytes(
        data=pdf_bytes,
        original_filename="minha_norma_local.pdf",
        expected_categories={MediaCategory.PDF},
    )
    assert res_pdf.category == MediaCategory.PDF


def test_blocks_decompression_bomb_exceeding_max_pixels() -> None:
    # Create an image with 2000x2000 = 4_000_000 pixels, then enforce max_image_pixels=1_000_000
    large_png = _make_png_bytes(2000, 2000)
    strict_settings = Settings(max_image_pixels=1_000_000)
    with pytest.raises(MediaSecurityError, match="Decompression bomb|exceeds decompression bomb"):
        validate_upload_bytes(
            data=large_png,
            original_filename="bomb.png",
            expected_categories={MediaCategory.IMAGE},
            settings=strict_settings,
        )


def test_blocks_path_traversal_and_null_bytes(temp_storage: Path) -> None:
    with pytest.raises(PathTraversalError):
        safe_storage_destination(temp_storage, "..", "..", "etc", "passwd")

    with pytest.raises(MediaSecurityError, match="Null byte"):
        sanitize_filename("panel\x00.png")

    # Directory components stripped safely
    assert sanitize_filename("../../evil/dir/photo final!.PNG") == "photo_final.png"


def test_atomic_write_replaces_without_leaving_tmp_files(temp_storage: Path) -> None:
    dest = temp_storage / "models_weights" / "active.pt"
    atomic_write_bytes(dest, b"v1-weights", base_dir=temp_storage)
    assert dest.read_bytes() == b"v1-weights"

    atomic_write_bytes(dest, b"v2-weights-updated", base_dir=temp_storage)
    assert dest.read_bytes() == b"v2-weights-updated"

    leftover_tmps = list((temp_storage / "models_weights").glob("*.tmp"))
    assert leftover_tmps == []
