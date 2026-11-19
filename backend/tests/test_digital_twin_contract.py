"""Contract tests for DigitalTwinJSON (Pydantic v2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.enums import CableColor, ComponentType, GroundingScheme, SupplySystem, TripCurve
from app.schemas.digital_twin import (
    BoundingBox,
    CableSpec,
    CircuitSpec,
    DigitalTwinJSON,
    OCRReading,
    PanelComponent,
    PanelMetadata,
)


def _make_valid_twin(detection_confidence: float = 0.95, ocr_confidence: float = 0.92) -> DigitalTwinJSON:
    return DigitalTwinJSON(
        project_id=uuid4(),
        inspection_id=uuid4(),
        panel=PanelMetadata(
            panel_id="QDC-01",
            name="Quadro Geral Residencial",
            supply_system=SupplySystem.BIFASICO_127_220V,
            grounding_scheme=GroundingScheme.TN_S,
            nominal_voltage_v=220.0,
            main_breaker_id="DJ-GERAL",
            has_idr=True,
            has_dps=True,
            has_pe_busbar=True,
            has_neutral_busbar=True,
        ),
        components=[
            PanelComponent(
                component_id="DJ-GERAL",
                label="Q1",
                component_type=ComponentType.DISJUNTOR_GERAL,
                poles=2,
                rated_current_a=50.0,
                trip_curve=TripCurve.C,
                breaking_capacity_ka=6.0,
                bbox=BoundingBox(x=0.1, y=0.1, w=0.2, h=0.3),
                detection_confidence=detection_confidence,
                ocr_reading=OCRReading(raw_text="C50 6kA", confidence=ocr_confidence),
            ),
            PanelComponent(
                component_id="IDR-01",
                label="IDR1",
                component_type=ComponentType.IDR,
                poles=2,
                rated_current_a=63.0,
                sensitivity_ma=30,
                parent_component_id="DJ-GERAL",
                detection_confidence=0.96,
            ),
            PanelComponent(
                component_id="DJ-C1",
                label="C1",
                component_type=ComponentType.DISJUNTOR_CIRCUITO,
                poles=1,
                rated_current_a=16.0,
                trip_curve=TripCurve.B,
                parent_component_id="IDR-01",
                detection_confidence=0.91,
            ),
        ],
        circuits=[
            CircuitSpec(
                circuit_id="CIRC-01",
                name="Iluminação Sala",
                circuit_kind="ILUMINACAO",
                phase_allocation="F1",
                voltage_v=127.0,
                load_power_va=1200.0,
                length_m=18.0,
                breaker_component_id="DJ-C1",
                idr_component_id="IDR-01",
                cable_phase_mm2=1.5,
                cable_neutral_mm2=1.5,
                cable_pe_mm2=1.5,
                cable_phase_color=CableColor.PRETO,
                cable_neutral_color=CableColor.AZUL_CLARO,
                cable_pe_color=CableColor.VERDE,
            )
        ],
    )


def test_low_detection_confidence_auto_flags_human_review() -> None:
    twin = _make_valid_twin(detection_confidence=0.72, ocr_confidence=0.95)
    main = twin.components[0]
    assert main.requires_human_review is True
    assert len(twin.pending_review_components()) == 1


def test_low_ocr_confidence_auto_flags_human_review() -> None:
    twin = _make_valid_twin(detection_confidence=0.95, ocr_confidence=0.65)
    main = twin.components[0]
    assert main.ocr_reading is not None
    assert main.ocr_reading.requires_human_review is True
    assert main.requires_human_review is True


def test_low_cable_color_confidence_auto_flags_human_review() -> None:
    comp = PanelComponent(
        component_id="CAB-01",
        label="N1",
        component_type=ComponentType.CABO_NEUTRO,
        detection_confidence=0.92,
        cable_spec=CableSpec(
            conductor_role="NEUTRO",
            section_mm2=2.5,
            color=CableColor.AZUL_CLARO,
            color_confidence=0.71,
        ),
    )
    assert comp.cable_spec is not None
    assert comp.cable_spec.requires_human_review is True
    assert comp.requires_human_review is True


def test_canonical_sha256_is_deterministic_and_timestamp_independent() -> None:
    twin1 = _make_valid_twin()
    twin2 = twin1.model_copy(
        update={
            "created_at": datetime.now(UTC) + timedelta(hours=1),
            "updated_at": datetime.now(UTC) + timedelta(hours=2),
        }
    )
    assert twin1.canonical_sha256() == twin2.canonical_sha256()

    # Mutating an engineering parameter MUST change the SHA-256 hash
    twin3 = twin1.model_copy(deep=True)
    twin3.circuits[0].cable_phase_mm2 = 2.5
    assert twin1.canonical_sha256() != twin3.canonical_sha256()


def test_rejects_broken_component_references_and_duplicate_ids() -> None:
    with pytest.raises(ValidationError, match="not found in components"):
        DigitalTwinJSON(
            project_id=uuid4(),
            inspection_id=uuid4(),
            panel=PanelMetadata(
                panel_id="QDC-ERR",
                name="Quadro Inválido",
                main_breaker_id="NON_EXISTENT",
            ),
            components=[],
        )

    with pytest.raises(ValidationError, match="Duplicate component_id"):
        DigitalTwinJSON(
            project_id=uuid4(),
            inspection_id=uuid4(),
            panel=PanelMetadata(panel_id="QDC-DUP", name="Quadro Duplicado"),
            components=[
                PanelComponent(
                    component_id="DUP-1",
                    label="D1",
                    component_type=ComponentType.DPS,
                ),
                PanelComponent(
                    component_id="DUP-1",
                    label="D2",
                    component_type=ComponentType.DPS,
                ),
            ],
        )


def test_rejects_out_of_bounds_bbox() -> None:
    with pytest.raises(ValidationError, match="exceeds normalized image bounds"):
        BoundingBox(x=0.8, y=0.2, w=0.3, h=0.2)
