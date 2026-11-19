"""MLOps Active Learning & Model Registry endpoints (`train_queue`)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.dataset_sample import DatasetSample, ModelVersion
from app.models.enums import DatasetSplit, InspectionStatus
from app.models.inspection import Inspection
from app.schemas.api import JobDispatchResponse
from app.schemas.digital_twin import DigitalTwinJSON
from app.services.ml_ops.dataset_builder import export_human_correction_sample

router = APIRouter(tags=["ml_ops"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


class TrainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    epochs: int = Field(default=20, ge=1, le=200)
    replay_ratio: float = Field(default=0.5, ge=0.0, le=2.0)


class HarvestStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_mb: int = Field(default=950, ge=1, le=950)
    sources: list[str] = Field(
        default_factory=lambda: ["wikimedia", "huggingface", "public_yolo", "cad_symbols"]
    )
    max_items_per_source: int = Field(default=1500, ge=1, le=10000)


class DatasetExportResponse(BaseModel):
    sample_id: UUID
    inspection_id: UUID
    image_path: str
    label_path: str
    class_counts: dict[str, int]


class ModelVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version_tag: str
    weights_path: str
    weights_sha256: str
    map50: float
    map50_95: float
    critical_recall_idr: float
    critical_recall_dps: float
    critical_recall_disjuntor: float
    is_active: bool
    promoted_at: datetime | None
    created_at: datetime


@router.post(
    "/ml/dataset/export/{inspection_id}",
    response_model=DatasetExportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def export_validated_inspection_to_dataset(
    inspection_id: UUID,
    db: DbSession,
    settings: AppSettings,
) -> DatasetExportResponse:
    """Export an ENGINEER_VALIDATED inspection's bounding boxes as a YOLO training sample."""
    inspection = await db.get(Inspection, inspection_id)
    if inspection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection not found.")

    if inspection.status not in {InspectionStatus.ENGINEER_VALIDATED, InspectionStatus.EXPORTED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only ENGINEER_VALIDATED or EXPORTED inspections may enter the Active Learning dataset.",
        )

    if not inspection.digital_twin_json or not inspection.source_media_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inspection lacks DigitalTwinJSON or source media.",
        )

    twin = DigitalTwinJSON.model_validate(inspection.digital_twin_json)
    source_path = Path(inspection.proxy_media_path or inspection.source_media_path)

    try:
        dest_img, dest_lbl, img_sha, class_counts = export_human_correction_sample(
            digital_twin=twin,
            source_image_path=source_path,
            staging_dir=settings.datasets_dir / "human_corrections",
            base_dir=settings.storage_root,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    sample = DatasetSample(
        inspection_id=inspection.id,
        image_path=str(dest_img),
        label_path=str(dest_lbl),
        image_sha256=img_sha,
        split=DatasetSplit.TRAIN,
        source="human_correction",
        is_locked_golden=False,
        class_counts_json=class_counts,
    )
    db.add(sample)
    await db.flush()
    await db.refresh(sample)

    return DatasetExportResponse(
        sample_id=sample.id,
        inspection_id=inspection.id,
        image_path=sample.image_path,
        label_path=sample.label_path,
        class_counts=class_counts,
    )


@router.post(
    "/ml/train",
    response_model=JobDispatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def dispatch_active_learning_training(payload: TrainRequest) -> JobDispatchResponse:
    """Dispatch Active Learning fine-tuning + Golden Holdout gatekeeper to `train_queue`."""
    async_result = celery_app.send_task(
        "app.services.ml_ops.yolo_trainer.run_active_learning_train_task",
        kwargs={"epochs": payload.epochs, "replay_ratio": payload.replay_ratio},
        queue="train_queue",
    )
    job_id = str(async_result.id)
    return JobDispatchResponse(
        job_id=job_id,
        queue="train_queue",
        status="QUEUED",
        sse_url=f"/api/v1/events/jobs/{job_id}",
    )


@router.post(
    "/ml/harvest/start",
    response_model=JobDispatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_public_dataset_harvest(payload: HarvestStartRequest) -> JobDispatchResponse:
    """Dispatch public electrical dataset harvesting (hard <= 950 MB quota) to `train_queue`."""
    async_result = celery_app.send_task(
        "app.services.ml_ops.harvester.pipeline.run_dataset_harvest_task",
        kwargs={
            "max_mb": payload.max_mb,
            "sources": payload.sources,
            "max_items_per_source": payload.max_items_per_source,
        },
        queue="train_queue",
    )
    job_id = str(async_result.id)
    return JobDispatchResponse(
        job_id=job_id,
        queue="train_queue",
        status="QUEUED",
        sse_url=f"/api/v1/events/jobs/{job_id}",
    )


@router.get("/ml/models", response_model=list[ModelVersionResponse])
async def list_model_versions(db: DbSession) -> list[ModelVersion]:
    """List all archived and active YOLO model versions with Golden Holdout metrics."""
    rows = await db.scalars(select(ModelVersion).order_by(ModelVersion.created_at.desc()))
    return list(rows.all())
