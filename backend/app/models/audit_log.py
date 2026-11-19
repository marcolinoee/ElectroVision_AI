"""Immutable AuditLog ORM model linking validated DigitalTwinJSON SHA-256 to exported artifacts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ArtifactType, InspectionStatus

if TYPE_CHECKING:
    from app.models.inspection import Inspection

JSONType = JSON().with_variant(JSONB(), "postgresql")


class AuditLog(Base):
    """Append-only compliance, sign-off, and artifact export audit trail (CREA/ART)."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    inspection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("inspections.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actor_crea: Mapped[str | None] = mapped_column(String(64), nullable=True)
    art_number: Mapped[str | None] = mapped_column(String(64), nullable=True)

    previous_status: Mapped[InspectionStatus | None] = mapped_column(
        Enum(InspectionStatus, native_enum=False, length=32), nullable=True
    )
    new_status: Mapped[InspectionStatus | None] = mapped_column(
        Enum(InspectionStatus, native_enum=False, length=32), nullable=True
    )

    digital_twin_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    artifact_type: Mapped[ArtifactType | None] = mapped_column(
        Enum(ArtifactType, native_enum=False, length=32), nullable=True
    )
    artifact_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    details_json: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    inspection: Mapped[Inspection | None] = relationship(back_populates="audit_logs")
