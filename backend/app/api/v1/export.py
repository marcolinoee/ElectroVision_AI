"""Compliance preview, Official Signed Export (`engine_queue`), and Local Norm PDF Import endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import (
    MediaCategory,
    MediaSecurityError,
    safe_storage_destination,
    validate_upload_bytes,
)
from app.core.storage import PathTraversalError, atomic_write_bytes
from app.models.inspection import Inspection
from app.schemas.api import ExportRequest, JobDispatchResponse
from app.schemas.digital_twin import DigitalTwinJSON
from app.schemas.state_machine import ExportSignOffError, InspectionStateMachine
from app.services.compliance.deterministic_engine import (
    ComplianceReport,
    evaluate_digital_twin_compliance,
)

router = APIRouter(tags=["export"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


class NormPdfImportResponse(BaseModel):
    standard_code: str
    filename: str
    sha256: str
    stored_path: str
    size_bytes: int


@router.post(
    "/inspections/{inspection_id}/compliance-preview",
    response_model=ComplianceReport,
)
async def preview_compliance_report(
    inspection_id: UUID,
    digital_twin: DigitalTwinJSON,
    db: DbSession,
) -> ComplianceReport:
    """Run deterministic NBR 5410 / NR-10 / NBR 14039 preview for engineer review before Sign-Off."""
    inspection = await db.get(Inspection, inspection_id)
    if inspection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection not found.")
    return evaluate_digital_twin_compliance(digital_twin)


@router.post(
    "/inspections/{inspection_id}/export",
    response_model=JobDispatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def dispatch_official_export(
    inspection_id: UUID,
    payload: ExportRequest,
    db: DbSession,
) -> JobDispatchResponse:
    """Enforce CREA/ART Sign-Off and dispatch official CAD/Doc export to `engine_queue`."""
    inspection = await db.get(Inspection, inspection_id)
    if inspection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection not found.")

    twin = (
        DigitalTwinJSON.model_validate(inspection.digital_twin_json)
        if inspection.digital_twin_json
        else None
    )

    try:
        InspectionStateMachine.assert_can_export(
            current_status=inspection.status,
            digital_twin=twin,
            stored_digital_twin_sha256=inspection.digital_twin_sha256,
            validated_by_crea=inspection.validated_by_crea,
        )
    except ExportSignOffError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    async_result = celery_app.send_task(
        "app.services.doc_engine.export_pipeline.run_official_export_task",
        args=[str(inspection.id), [a.value for a in payload.artifacts]],
        queue="engine_queue",
    )
    job_id = str(async_result.id)
    return JobDispatchResponse(
        job_id=job_id,
        queue="engine_queue",
        status="QUEUED",
        sse_url=f"/api/v1/events/jobs/{job_id}",
    )


@router.post(
    "/norms/import-pdf",
    response_model=NormPdfImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_local_norm_pdf(
    settings: AppSettings,
    standard_code: Annotated[str, Form(...)],
    file: Annotated[UploadFile, File(...)],
) -> NormPdfImportResponse:
    """Store a user-supplied normative PDF locally for pgvector indexing (copyright-compliant)."""
    raw_bytes = await file.read()
    try:
        validated = validate_upload_bytes(
            data=raw_bytes,
            original_filename=file.filename or "norma.pdf",
            expected_categories={MediaCategory.PDF},
            settings=settings,
        )
        dest_path = safe_storage_destination(
            settings.norms_pdfs_dir,
            validated.sanitized_filename,
        )
        atomic_write_bytes(dest_path, raw_bytes, base_dir=settings.storage_root)
    except (MediaSecurityError, PathTraversalError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return NormPdfImportResponse(
        standard_code=standard_code.strip(),
        filename=validated.sanitized_filename,
        sha256=validated.sha256,
        stored_path=str(dest_path),
        size_bytes=validated.size_bytes,
    )
