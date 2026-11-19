"""Project ORM model."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Float, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import GroundingScheme, SupplySystem

if TYPE_CHECKING:
    from app.models.inspection import Inspection


class Project(Base):
    """Electrical engineering project / facility container."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    client_name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    installation_type: Mapped[str] = mapped_column(String(80), nullable=False, default="RESIDENCIAL")
    supply_system: Mapped[SupplySystem] = mapped_column(
        Enum(SupplySystem, native_enum=False, length=40),
        nullable=False,
        default=SupplySystem.BIFASICO_127_220V,
    )
    grounding_scheme: Mapped[GroundingScheme] = mapped_column(
        Enum(GroundingScheme, native_enum=False, length=16),
        nullable=False,
        default=GroundingScheme.TN_S,
    )
    nominal_voltage_v: Mapped[float] = mapped_column(Float, nullable=False, default=220.0)
    base_dxf_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    engineer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    engineer_crea: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    inspections: Mapped[list[Inspection]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
