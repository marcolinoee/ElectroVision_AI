"""Secure AppSec media & architectural DXF upload endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import (
    MediaCategory,
    MediaSecurityError,
    safe_storage_destination,
    validate_upload_bytes,
)
from app.core.storage import PathTraversalError, atomic_write_bytes
from app.models.audit_log import AuditLog
from app.models.inspection import Inspection
from app.models.project import Project
from app.services.vision.proxy_gen import generate_image_proxies

router = APIRouter(tags=["upload"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


class MediaUploadResponse(BaseModel):
    inspection_id: UUID
    category: str
    detected_mime: str
    size_bytes: int
    sha256: str
    source_media_path: str
    proxy_media_path: str | None = None
    thumbnail_media_path: str | None = None


class BaseDxfUploadResponse(BaseModel):
    project_id: UUID
    size_bytes: int
    sha256: str
    base_dxf_path: str


@router.post(
    "/inspections/{inspection_id}/upload-media",
    response_model=MediaUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_inspection_media(
    inspection_id: UUID,
    db: DbSession,
    settings: AppSettings,
    file: Annotated[UploadFile, File(...)],
) -> MediaUploadResponse:
    """Validate and atomically store an inspection photo or video (magic bytes + bomb guard)."""
    inspection = await db.get(Inspection, inspection_id)
    if inspection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection not found.")

    raw_bytes = await file.read()
    try:
        validated = validate_upload_bytes(
            data=raw_bytes,
            original_filename=file.filename or "upload.bin",
            expected_categories={MediaCategory.IMAGE, MediaCategory.VIDEO},
            settings=settings,
        )
        dest_path = safe_storage_destination(
            settings.uploads_dir,
            str(inspection_id),
            validated.sanitized_filename,
        )
        atomic_write_bytes(dest_path, raw_bytes, base_dir=settings.storage_root)
    except (MediaSecurityError, PathTraversalError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    proxy_path_str: str | None = None
    thumb_path_str: str | None = None
    if validated.category == MediaCategory.IMAGE:
        proxies = generate_image_proxies(
            source_image_path=dest_path,
            output_dir=settings.proxies_dir / str(inspection_id),
            stem=str(inspection_id),
            base_dir=settings.storage_root,
        )
        proxy_path_str = str(proxies.proxy_path)
        thumb_path_str = str(proxies.thumbnail_path)

    inspection.source_media_path = str(dest_path)
    inspection.source_media_sha256 = validated.sha256
    if proxy_path_str:
        inspection.proxy_media_path = proxy_path_str

    db.add(
        AuditLog(
            project_id=inspection.project_id,
            inspection_id=inspection.id,
            event_type="MEDIA_UPLOADED",
            artifact_path=str(dest_path),
            artifact_sha256=validated.sha256,
            details_json={
                "category": validated.category.value,
                "detected_mime": validated.detected_mime,
                "size_bytes": validated.size_bytes,
            },
        )
    )
    await db.flush()

    return MediaUploadResponse(
        inspection_id=inspection.id,
        category=validated.category.value,
        detected_mime=validated.detected_mime,
        size_bytes=validated.size_bytes,
        sha256=validated.sha256,
        source_media_path=str(dest_path),
        proxy_media_path=proxy_path_str,
        thumbnail_media_path=thumb_path_str,
    )


@router.post(
    "/projects/{project_id}/upload-dxf",
    response_model=BaseDxfUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_project_base_dxf(
    project_id: UUID,
    db: DbSession,
    settings: AppSettings,
    file: Annotated[UploadFile, File(...)],
) -> BaseDxfUploadResponse:
    """Validate and atomically store an architectural base .DXF for Planta Elétrica overlay."""
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    raw_bytes = await file.read()
    try:
        validated = validate_upload_bytes(
            data=raw_bytes,
            original_filename=file.filename or "base.dxf",
            expected_categories={MediaCategory.DXF},
            settings=settings,
        )
        dest_path: Path = safe_storage_destination(
            settings.uploads_dir,
            "base_dxf",
            str(project_id),
            validated.sanitized_filename,
        )
        atomic_write_bytes(dest_path, raw_bytes, base_dir=settings.storage_root)
    except (MediaSecurityError, PathTraversalError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    project.base_dxf_path = str(dest_path)
    db.add(
        AuditLog(
            project_id=project.id,
            event_type="BASE_DXF_UPLOADED",
            artifact_path=str(dest_path),
            artifact_sha256=validated.sha256,
            details_json={"size_bytes": validated.size_bytes},
        )
    )
    await db.flush()

    return BaseDxfUploadResponse(
        project_id=project.id,
        size_bytes=validated.size_bytes,
        sha256=validated.sha256,
        base_dxf_path=str(dest_path),
    )
