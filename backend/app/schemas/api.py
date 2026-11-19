"""Pydantic v2 API request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    ArtifactType,
    GroundingScheme,
    InspectionStatus,
    SupplySystem,
)
from app.schemas.digital_twin import DigitalTwinJSON
from app.schemas.state_machine import SignOffCredentials


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    device: str


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=2, max_length=200)
    client_name: str = Field(..., min_length=2, max_length=200)
    address: str | None = None
    installation_type: str = Field(default="RESIDENCIAL", max_length=80)
    supply_system: SupplySystem = SupplySystem.BIFASICO_127_220V
    grounding_scheme: GroundingScheme = GroundingScheme.TN_S
    nominal_voltage_v: float = Field(default=220.0, gt=0.0, le=36000.0)
    engineer_name: str | None = Field(default=None, max_length=200)
    engineer_crea: str | None = Field(default=None, max_length=64)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    client_name: str
    address: str | None
    installation_type: str
    supply_system: SupplySystem
    grounding_scheme: GroundingScheme
    nominal_voltage_v: float
    base_dxf_path: str | None
    engineer_name: str | None
    engineer_crea: str | None
    created_at: datetime
    updated_at: datetime


class InspectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    title: str = Field(..., min_length=2, max_length=200)


class InspectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    title: str
    status: InspectionStatus
    source_media_path: str | None
    proxy_media_path: str | None
    digital_twin_json: dict[str, Any] | None
    digital_twin_sha256: str | None
    validated_by_name: str | None
    validated_by_crea: str | None
    art_number: str | None
    validated_at: datetime | None
    exported_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SignOffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credentials: SignOffCredentials
    digital_twin: DigitalTwinJSON


class SignOffResponse(BaseModel):
    inspection_id: UUID
    status: InspectionStatus
    digital_twin_sha256: str
    validated_by_name: str
    validated_by_crea: str
    art_number: str | None
    validated_at: datetime


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifacts: list[ArtifactType] = Field(
        default_factory=lambda: [
            ArtifactType.UNIFILAR_DXF,
            ArtifactType.UNIFILAR_SVG,
            ArtifactType.MEMORIAL_DOCX,
            ArtifactType.RETROFIT_XLSX,
        ],
        min_length=1,
    )


class JobDispatchResponse(BaseModel):
    job_id: str
    queue: str
    status: str
    sse_url: str
