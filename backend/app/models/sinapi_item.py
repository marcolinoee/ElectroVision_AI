"""SINAPI electrical composition items for deterministic retrofit budgeting."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


class SinapiItem(Base):
    """Structured SINAPI electrical catalog item."""

    __tablename__ = "sinapi_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sinapi_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    unit_price_brl: Mapped[float] = mapped_column(Float, nullable=False)
    reference_month: Mapped[str] = mapped_column(String(16), nullable=False, default="2025-01")
    state_uf: Mapped[str] = mapped_column(String(4), nullable=False, default="SP")
    material_specs_json: Mapped[dict[str, Any]] = mapped_column(
        JSONType, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
