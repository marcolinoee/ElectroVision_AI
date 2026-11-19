"""Inspection ORM model with rigid CREA/ART sign-off state & DigitalTwinJSON persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import InspectionStatus

if TYPE_CHECKING:
    from app.models.audit_log import AuditLog
    from app.models.component import Component
    from app.models.project import Project

JSONType = JSON().with_variant(JSONB(), "postgresql")


class Inspection(Base):
    """Single panel/site inspection lifecycle from DRAFT to EXPORTED."""

    __tablename__ = "inspections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[InspectionStatus] = mapped_column(
        Enum(InspectionStatus, native_enum=False, length=32),
        nullable=False,
        default=InspectionStatus.DRAFT,
        index=True,
    )
    source_media_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_media_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proxy_media_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    digital_twin_json: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    digital_twin_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    compliance_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    # Human Engineer Sign-Off (CREA / ART)
    validated_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    validated_by_crea: Mapped[str | None] = mapped_column(String(64), nullable=True)
    art_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    project: Mapped[Project] = relationship(back_populates="inspections")
    components: Mapped[list[Component]] = relationship(
        back_populates="inspection", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list[AuditLog]] = relationship(
        back_populates="inspection", cascade="all, delete-orphan"
    )
