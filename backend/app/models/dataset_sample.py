"""Active Learning dataset samples & atomic YOLO model registry ORM models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import DatasetSplit

JSONType = JSON().with_variant(JSONB(), "postgresql")


class DatasetSample(Base):
    """YOLO training/validation/Golden Holdout dataset sample with replay buffer tracking."""

    __tablename__ = "dataset_samples"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inspection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("inspections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    image_path: Mapped[str] = mapped_column(String(512), nullable=False)
    label_path: Mapped[str] = mapped_column(String(512), nullable=False)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    split: Mapped[DatasetSplit] = mapped_column(
        Enum(DatasetSplit, native_enum=False, length=32),
        nullable=False,
        default=DatasetSplit.TRAIN,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="human_correction")
    is_locked_golden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    class_counts_json: Mapped[dict[str, int]] = mapped_column(
        JSONType, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class ModelVersion(Base):
    """Immutable registry of trained YOLO .pt weights and Golden Holdout Set evaluation metrics."""

    __tablename__ = "model_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_tag: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    weights_path: Mapped[str] = mapped_column(String(512), nullable=False)
    weights_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    map50: Mapped[float] = mapped_column(Float, nullable=False)
    map50_95: Mapped[float] = mapped_column(Float, nullable=False)
    critical_recall_idr: Mapped[float] = mapped_column(Float, nullable=False)
    critical_recall_dps: Mapped[float] = mapped_column(Float, nullable=False)
    critical_recall_disjuntor: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
