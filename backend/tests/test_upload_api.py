"""Integration tests for Phase 2 Upload API endpoints (AppSec magic bytes + atomic proxy gen)."""

from __future__ import annotations

import io
from pathlib import Path

from httpx import AsyncClient
from PIL import Image

from app.core.config import Settings, get_settings
from app.main import app


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), color=(40, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


async def test_upload_media_and_base_dxf_endpoints(
    api_client: AsyncClient,
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage"
    test_settings = Settings(storage_root=storage_root)
    test_settings.ensure_storage_directories()
    app.dependency_overrides[get_settings] = lambda: test_settings

    try:
        proj = await api_client.post(
            "/api/v1/projects",
            json={"name": "Projeto Upload", "client_name": "Cliente Teste"},
        )
        assert proj.status_code == 201
        project_id = proj.json()["id"]

        insp = await api_client.post(
            "/api/v1/inspections",
            json={"project_id": project_id, "title": "QDC Principal"},
        )
        assert insp.status_code == 201
        inspection_id = insp.json()["id"]

        # 1. Valid PNG upload succeeds and generates proxy + thumbnail
        up_ok = await api_client.post(
            f"/api/v1/inspections/{inspection_id}/upload-media",
            files={"file": ("quadro_01.png", _png_bytes(), "image/png")},
        )
        assert up_ok.status_code == 201
        body = up_ok.json()
        assert body["category"] == "image"
        assert Path(body["source_media_path"]).exists()
        assert Path(body["proxy_media_path"]).exists()
        assert Path(body["thumbnail_media_path"]).exists()

        # 2. Spoofed executable disguised as .jpg is rejected with 400
        up_bad = await api_client.post(
            f"/api/v1/inspections/{inspection_id}/upload-media",
            files={"file": ("malware.jpg", b"MZ\x90\x00not-a-jpeg-file", "image/jpeg")},
        )
        assert up_bad.status_code == 400

        # 3. Valid ASCII DXF upload for project succeeds
        dxf_bytes = b"  0\r\nSECTION\r\n  2\r\nHEADER\r\n  0\r\nENDSEC\r\n  0\r\nEOF\r\n"
        dxf_ok = await api_client.post(
            f"/api/v1/projects/{project_id}/upload-dxf",
            files={"file": ("arquitetura.dxf", dxf_bytes, "application/dxf")},
        )
        assert dxf_ok.status_code == 201
        assert Path(dxf_ok.json()["base_dxf_path"]).exists()

        # 4. PNG disguised as .dxf is rejected with 400
        dxf_bad = await api_client.post(
            f"/api/v1/projects/{project_id}/upload-dxf",
            files={"file": ("fake.dxf", _png_bytes(), "application/dxf")},
        )
        assert dxf_bad.status_code == 400
    finally:
        app.dependency_overrides.pop(get_settings, None)
