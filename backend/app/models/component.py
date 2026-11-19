"""Detected/validated electrical component ORM model."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import CableColor, ComponentType, TripCurve

if TYPE_CHECKING:
    from app.models.inspection import Inspection

JSONType = JSON().with_variant(JSONB(), "postgresql")


class Component(Base):
    """Normalized relational projection of electrical components inside an Inspection."""

    __tablename__ = "components"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inspection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("inspections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label_code: Mapped[str] = mapped_column(String(64), nullable=False)
    component_type: Mapped[ComponentType] = mapped_column(
        Enum(ComponentType, native_enum=False, length=40), nullable=False, index=True
    )
    manufacturer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    rated_current_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    trip_curve: Mapped[TripCurve | None] = mapped_column(
        Enum(TripCurve, native_enum=False, length=8), nullable=True
    )
    breaking_capacity_ka: Mapped[float | None] = mapped_column(Float, nullable=True)
    poles: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sensitivity_ma: Mapped[int | None] = mapped_column(Integer, nullable=True)

    cable_section_mm2: Mapped[float | None] = mapped_column(Float, nullable=True)
    cable_color: Mapped[CableColor | None] = mapped_column(
        Enum(CableColor, native_enum=False, length=24), nullable=True
    )

    # Normalized bounding box [0.0 .. 1.0]
    bbox_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_h: Mapped[float | None] = mapped_column(Float, nullable=True)

    detection_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ocr_text: Mapped[str | None] = mapped_column(String(256), nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    verified_by_human: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    inspection: Mapped[Inspection] = relationship(back_populates="components")
