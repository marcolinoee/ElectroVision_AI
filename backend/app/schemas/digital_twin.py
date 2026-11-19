"""Strict Pydantic v2 contract for the validated Electrical Digital Twin (DigitalTwinJSON)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.security import compute_canonical_json_sha256
from app.models.enums import (
    CableColor,
    ComponentType,
    GroundingScheme,
    SupplySystem,
    TripCurve,
)

CONFIDENCE_REVIEW_THRESHOLD: float = 0.80


class BoundingBox(BaseModel):
    """Normalized [0.0..1.0] bounding box in top-left (x, y, w, h) format."""

    model_config = ConfigDict(extra="forbid")

    x: float = Field(..., ge=0.0, le=1.0, description="Normalized left X coordinate.")
    y: float = Field(..., ge=0.0, le=1.0, description="Normalized top Y coordinate.")
    w: float = Field(..., gt=0.0, le=1.0, description="Normalized width.")
    h: float = Field(..., gt=0.0, le=1.0, description="Normalized height.")

    @model_validator(mode="after")
    def validate_bounds(self) -> BoundingBox:
        if self.x + self.w > 1.001 or self.y + self.h > 1.001:
            raise ValueError("BoundingBox exceeds normalized image bounds [0.0, 1.0].")
        return self


class OCRReading(BaseModel):
    """OCR reading from component faceplate (e.g. 'C20', '30mA', '275V 20kA')."""

    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(..., min_length=1, max_length=256)
    normalized_text: str | None = Field(default=None, max_length=256)
    confidence: float = Field(..., ge=0.0, le=1.0)
    requires_human_review: bool = Field(default=False)

    @model_validator(mode="after")
    def enforce_confidence_flag(self) -> OCRReading:
        if self.confidence < CONFIDENCE_REVIEW_THRESHOLD:
            self.requires_human_review = True
        return self


class CableSpec(BaseModel):
    """Conductor specification extracted via vision color analysis and/or human input."""

    model_config = ConfigDict(extra="forbid")

    conductor_role: Literal["FASE", "NEUTRO", "TERRA_PE", "PEN", "RETORNO"]
    section_mm2: float | None = Field(default=None, gt=0.0, le=1000.0)
    insulation_type: Literal["PVC_70C", "EPR_90C", "XLPE_90C"] = "PVC_70C"
    color: CableColor = CableColor.DESCONHECIDA
    color_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    requires_human_review: bool = Field(default=False)

    @model_validator(mode="after")
    def enforce_color_confidence(self) -> CableSpec:
        if self.color_confidence < CONFIDENCE_REVIEW_THRESHOLD:
            self.requires_human_review = True
        return self


class PanelComponent(BaseModel):
    """Single electrical component inside a panel or distribution board."""

    model_config = ConfigDict(extra="forbid")

    component_id: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=64)
    component_type: ComponentType
    manufacturer: str | None = Field(default=None, max_length=120)
    model_name: str | None = Field(default=None, max_length=120)

    # Protection & electrical ratings
    poles: int | None = Field(default=None, ge=1, le=4)
    rated_current_a: float | None = Field(default=None, gt=0.0, le=6300.0)
    trip_curve: TripCurve | None = None
    breaking_capacity_ka: float | None = Field(default=None, gt=0.0, le=150.0)
    sensitivity_ma: int | None = Field(default=None, ge=10, le=1000)

    # DPS specific ratings
    dps_class: Literal["I", "II", "III", "I+II"] | None = None
    dps_uc_v: float | None = Field(default=None, gt=0.0, le=1500.0)
    dps_imax_ka: float | None = Field(default=None, gt=0.0, le=200.0)

    # Cable / terminal details
    cable_spec: CableSpec | None = None

    # Vision & OCR metadata
    bbox: BoundingBox | None = None
    detection_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    ocr_reading: OCRReading | None = None
    requires_human_review: bool = Field(default=False)
    verified_by_human: bool = Field(default=False)

    # Topology reference (e.g., circuit breaker fed by IDR or main breaker)
    parent_component_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def enforce_review_threshold(self) -> PanelComponent:
        low_det = self.detection_confidence < CONFIDENCE_REVIEW_THRESHOLD
        low_ocr = self.ocr_reading is not None and self.ocr_reading.requires_human_review
        low_cable = self.cable_spec is not None and self.cable_spec.requires_human_review
        if low_det or low_ocr or low_cable:
            self.requires_human_review = True
        return self


class CircuitSpec(BaseModel):
    """Terminal or distribution circuit specification for deterministic NBR 5410 evaluation."""

    model_config = ConfigDict(extra="forbid")

    circuit_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=120)
    circuit_kind: Literal["ILUMINACAO", "TOMADAS_USO_GERAL", "TUE", "MOTOR", "DISTRIBUICAO"]
    phase_allocation: Literal["F1", "F2", "F3", "F1-F2", "F2-F3", "F3-F1", "F1-F2-F3"] = "F1"
    voltage_v: float = Field(..., gt=0.0, le=36000.0)
    load_power_va: float = Field(..., gt=0.0, le=5_000_000.0)
    power_factor: float = Field(default=0.92, gt=0.0, le=1.0)
    length_m: float = Field(..., gt=0.0, le=2000.0)
    installation_method: Literal["A1", "A2", "B1", "B2", "C", "D"] = "B1"
    ambient_temp_c: float = Field(default=30.0, ge=10.0, le=60.0)
    grouping_count: int = Field(default=1, ge=1, le=20)
    is_wet_area: bool = False
    is_external_area: bool = False

    breaker_component_id: str | None = Field(default=None, max_length=64)
    idr_component_id: str | None = Field(default=None, max_length=64)

    cable_phase_mm2: float = Field(..., gt=0.0, le=500.0)
    cable_neutral_mm2: float | None = Field(default=None, gt=0.0, le=500.0)
    cable_pe_mm2: float | None = Field(default=None, gt=0.0, le=500.0)
    cable_phase_color: CableColor = CableColor.PRETO
    cable_neutral_color: CableColor | None = CableColor.AZUL_CLARO
    cable_pe_color: CableColor | None = CableColor.VERDE

    # Optional spatial coordinates on calibrated floor plan (meters)
    plan_x_m: float | None = None
    plan_y_m: float | None = None


class PanelMetadata(BaseModel):
    """Macro electrical & physical characteristics of the inspected distribution board."""

    model_config = ConfigDict(extra="forbid")

    panel_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=120)
    location: str = Field(default="QDC Principal", max_length=200)
    supply_system: SupplySystem = SupplySystem.BIFASICO_127_220V
    grounding_scheme: GroundingScheme = GroundingScheme.TN_S
    nominal_voltage_v: float = Field(default=220.0, gt=0.0, le=36000.0)
    main_breaker_id: str | None = Field(default=None, max_length=64)

    has_idr: bool = False
    has_dps: bool = False
    has_pe_busbar: bool = False
    has_neutral_busbar: bool = False
    pe_neutral_separated: bool = True
    door_grounding_present: bool = False
    warning_sign_nr10_present: bool = False
    unifilar_diagram_inside_present: bool = False
    ip_rating: str | None = Field(default=None, max_length=16)


class SpatialCalibration(BaseModel):
    """Floor-plan DXF calibration metadata — required before Planta Elétrica DXF overlay."""

    model_config = ConfigDict(extra="forbid")

    base_dxf_path: str = Field(..., min_length=1, max_length=512)
    origin_x: float = 0.0
    origin_y: float = 0.0
    scale_px_per_meter: float = Field(..., gt=0.0)
    calibrated_by_human: bool = False


class DigitalTwinJSON(BaseModel):
    """Canonical, deterministic contract shared by Vision, Compliance, CAD, Doc, and Frontend."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"] = "1.0.0"
    project_id: UUID
    inspection_id: UUID
    panel: PanelMetadata
    components: list[PanelComponent] = Field(default_factory=list)
    circuits: list[CircuitSpec] = Field(default_factory=list)
    spatial_calibration: SpatialCalibration | None = None
    source_image_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("components")
    @classmethod
    def unique_component_ids(cls, values: list[PanelComponent]) -> list[PanelComponent]:
        seen: set[str] = set()
        for comp in values:
            if comp.component_id in seen:
                raise ValueError(f"Duplicate component_id detected: '{comp.component_id}'.")
            seen.add(comp.component_id)
        return values

    @field_validator("circuits")
    @classmethod
    def unique_circuit_ids(cls, values: list[CircuitSpec]) -> list[CircuitSpec]:
        seen: set[str] = set()
        for circ in values:
            if circ.circuit_id in seen:
                raise ValueError(f"Duplicate circuit_id detected: '{circ.circuit_id}'.")
            seen.add(circ.circuit_id)
        return values

    @model_validator(mode="after")
    def validate_component_references(self) -> DigitalTwinJSON:
        comp_ids = {c.component_id for c in self.components}
        if self.panel.main_breaker_id and self.panel.main_breaker_id not in comp_ids:
            raise ValueError(
                f"panel.main_breaker_id '{self.panel.main_breaker_id}' not found in components."
            )
        for comp in self.components:
            if comp.parent_component_id and comp.parent_component_id not in comp_ids:
                raise ValueError(
                    f"Component '{comp.component_id}' references unknown parent "
                    f"'{comp.parent_component_id}'."
                )
        for circ in self.circuits:
            if circ.breaker_component_id and circ.breaker_component_id not in comp_ids:
                raise ValueError(
                    f"Circuit '{circ.circuit_id}' references unknown breaker "
                    f"'{circ.breaker_component_id}'."
                )
            if circ.idr_component_id and circ.idr_component_id not in comp_ids:
                raise ValueError(
                    f"Circuit '{circ.circuit_id}' references unknown IDR '{circ.idr_component_id}'."
                )
        return self

    def pending_review_components(self) -> list[PanelComponent]:
        """Return components flagged for human review that have not yet been verified."""
        return [
            c for c in self.components if c.requires_human_review and not c.verified_by_human
        ]

    def canonical_payload(self) -> dict[str, object]:
        """Return timestamp-independent canonical dict for deterministic SHA-256 signing."""
        data = self.model_dump(mode="json")
        # Exclude mutable wall-clock metadata so identical engineering state yields identical hash
        data.pop("created_at", None)
        data.pop("updated_at", None)
        return data

    def canonical_sha256(self) -> str:
        """Compute deterministic SHA-256 hash of the engineering Digital Twin state."""
        return compute_canonical_json_sha256(self.canonical_payload())
