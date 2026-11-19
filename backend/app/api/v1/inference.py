"""Computer Vision inference dispatch endpoint (queues work to isolated worker-ml)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.core.database import get_db
from app.models.enums import InspectionStatus
from app.models.inspection import Inspection
from app.schemas.api import JobDispatchResponse
from app.schemas.state_machine import InspectionStateMachine, StateTransitionError

router = APIRouter(tags=["inference"])
DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/inspections/{inspection_id}/infer",
    response_model=JobDispatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def dispatch_vision_inference(
    inspection_id: UUID,
    db: DbSession,
) -> JobDispatchResponse:
    """Dispatch YOLO + OCR + Color Analysis pipeline to `vision_queue` on `worker-ml`."""
    inspection = await db.get(Inspection, inspection_id)
    if inspection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection not found.")

    if not inspection.source_media_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload inspection photo or video before requesting AI inference.",
        )

    try:
        InspectionStateMachine.assert_transition(
            inspection.status, InspectionStatus.AI_PROCESSED
        )
    except StateTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    async_result = celery_app.send_task(
        "app.services.vision.pipeline.run_inspection_vision_task",
        args=[str(inspection.id)],
        queue="vision_queue",
    )
    job_id = str(async_result.id)
    return JobDispatchResponse(
        job_id=job_id,
        queue="vision_queue",
        status="QUEUED",
        sse_url=f"/api/v1/events/jobs/{job_id}",
    )
