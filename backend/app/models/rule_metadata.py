"""Normative rule metadata (no copyrighted ABNT full text) & user-imported pgvector NormChunk."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, DateTime, Enum, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import SeverityLevel

JSONType = JSON().with_variant(JSONB(), "postgresql")
EmbeddingVectorType = JSON().with_variant(Vector(384), "postgresql")


class RuleMetadata(Base):
    """Structured deterministic rule parameters for NBR 5410, NR-10, and NBR 14039.

    IMPORTANT (Copyright Guardrail): Stores ONLY structured engineering parameters
    and technical checklists — never full copyrighted ABNT text.
    """

    __tablename__ = "rule_metadata"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    standard_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    section_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    severity: Mapped[SeverityLevel] = mapped_column(
        Enum(SeverityLevel, native_enum=False, length=24),
        nullable=False,
        default=SeverityLevel.ALTA,
    )
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    check_summary: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class NormChunk(Base):
    """Locally indexed chunk from user-supplied normative PDFs for pgvector RAG citations.

    Populated exclusively from PDFs imported locally by the user into ./storage/norms_pdfs.
    Embedding dimension = 384 (intfloat/multilingual-e5-small ONNX).
    """

    __tablename__ = "norm_chunks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    standard_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    document_filename: Mapped[str] = mapped_column(String(256), nullable=False)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(EmbeddingVectorType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
