"""Initial ElectroVision AI schema with PostgreSQL 16 + pgvector.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-18 22:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("client_name", sa.String(length=200), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("installation_type", sa.String(length=80), nullable=False),
        sa.Column("supply_system", sa.String(length=40), nullable=False),
        sa.Column("grounding_scheme", sa.String(length=16), nullable=False),
        sa.Column("nominal_voltage_v", sa.Float(), nullable=False),
        sa.Column("base_dxf_path", sa.String(length=512), nullable=True),
        sa.Column("engineer_name", sa.String(length=200), nullable=True),
        sa.Column("engineer_crea", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_projects_name", "projects", ["name"])

    op.create_table(
        "inspections",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_media_path", sa.String(length=512), nullable=True),
        sa.Column("source_media_sha256", sa.String(length=64), nullable=True),
        sa.Column("proxy_media_path", sa.String(length=512), nullable=True),
        sa.Column("digital_twin_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("digital_twin_sha256", sa.String(length=64), nullable=True),
        sa.Column("compliance_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("validated_by_name", sa.String(length=200), nullable=True),
        sa.Column("validated_by_crea", sa.String(length=64), nullable=True),
        sa.Column("art_number", sa.String(length=64), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_inspections_project_id", "inspections", ["project_id"])
    op.create_index("ix_inspections_status", "inspections", ["status"])
    op.create_index("ix_inspections_digital_twin_sha256", "inspections", ["digital_twin_sha256"])

    op.create_table(
        "components",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "inspection_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("inspections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label_code", sa.String(length=64), nullable=False),
        sa.Column("component_type", sa.String(length=40), nullable=False),
        sa.Column("manufacturer", sa.String(length=120), nullable=True),
        sa.Column("model_name", sa.String(length=120), nullable=True),
        sa.Column("rated_current_a", sa.Float(), nullable=True),
        sa.Column("trip_curve", sa.String(length=8), nullable=True),
        sa.Column("breaking_capacity_ka", sa.Float(), nullable=True),
        sa.Column("poles", sa.Integer(), nullable=True),
        sa.Column("sensitivity_ma", sa.Integer(), nullable=True),
        sa.Column("cable_section_mm2", sa.Float(), nullable=True),
        sa.Column("cable_color", sa.String(length=24), nullable=True),
        sa.Column("bbox_x", sa.Float(), nullable=True),
        sa.Column("bbox_y", sa.Float(), nullable=True),
        sa.Column("bbox_w", sa.Float(), nullable=True),
        sa.Column("bbox_h", sa.Float(), nullable=True),
        sa.Column("detection_confidence", sa.Float(), nullable=False),
        sa.Column("ocr_text", sa.String(length=256), nullable=True),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("requires_human_review", sa.Boolean(), nullable=False),
        sa.Column("verified_by_human", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_components_inspection_id", "components", ["inspection_id"])
    op.create_index("ix_components_component_type", "components", ["component_type"])

    op.create_table(
        "rule_metadata",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("rule_code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("standard_code", sa.String(length=64), nullable=False),
        sa.Column("section_ref", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=24), nullable=False),
        sa.Column("parameters_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("check_summary", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_rule_metadata_standard_code", "rule_metadata", ["standard_code"])
    op.create_index("ix_rule_metadata_category", "rule_metadata", ["category"])

    op.create_table(
        "norm_chunks",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("standard_code", sa.String(length=64), nullable=False),
        sa.Column("document_filename", sa.String(length=256), nullable=False),
        sa.Column("document_sha256", sa.String(length=64), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_norm_chunks_standard_code", "norm_chunks", ["standard_code"])
    op.create_index("ix_norm_chunks_document_sha256", "norm_chunks", ["document_sha256"])
    op.execute(
        "CREATE INDEX ix_norm_chunks_embedding_hnsw ON norm_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "sinapi_items",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("sinapi_code", sa.String(length=32), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("unit_price_brl", sa.Float(), nullable=False),
        sa.Column("reference_month", sa.String(length=16), nullable=False),
        sa.Column("state_uf", sa.String(length=4), nullable=False),
        sa.Column("material_specs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sinapi_items_category", "sinapi_items", ["category"])

    op.create_table(
        "dataset_samples",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "inspection_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("inspections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("image_path", sa.String(length=512), nullable=False),
        sa.Column("label_path", sa.String(length=512), nullable=False),
        sa.Column("image_sha256", sa.String(length=64), nullable=False),
        sa.Column("split", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("is_locked_golden", sa.Boolean(), nullable=False),
        sa.Column("class_counts_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dataset_samples_split", "dataset_samples", ["split"])
    op.create_index("ix_dataset_samples_image_sha256", "dataset_samples", ["image_sha256"])

    op.create_table(
        "model_versions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("version_tag", sa.String(length=64), nullable=False, unique=True),
        sa.Column("weights_path", sa.String(length=512), nullable=False),
        sa.Column("weights_sha256", sa.String(length=64), nullable=False),
        sa.Column("map50", sa.Float(), nullable=False),
        sa.Column("map50_95", sa.Float(), nullable=False),
        sa.Column("critical_recall_idr", sa.Float(), nullable=False),
        sa.Column("critical_recall_dps", sa.Float(), nullable=False),
        sa.Column("critical_recall_disjuntor", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_model_versions_is_active", "model_versions", ["is_active"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "inspection_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("inspections.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("actor_crea", sa.String(length=64), nullable=True),
        sa.Column("art_number", sa.String(length=64), nullable=True),
        sa.Column("previous_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=True),
        sa.Column("digital_twin_sha256", sa.String(length=64), nullable=True),
        sa.Column("artifact_type", sa.String(length=32), nullable=True),
        sa.Column("artifact_path", sa.String(length=512), nullable=True),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_inspection_id", "audit_logs", ["inspection_id"])
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"])
    op.create_index("ix_audit_logs_digital_twin_sha256", "audit_logs", ["digital_twin_sha256"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("model_versions")
    op.drop_table("dataset_samples")
    op.drop_table("sinapi_items")
    op.drop_table("norm_chunks")
    op.drop_table("rule_metadata")
    op.drop_table("components")
    op.drop_table("inspections")
    op.drop_table("projects")
