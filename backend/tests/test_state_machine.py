"""Tests for the rigid CREA/ART Sign-Off State Machine."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.enums import ComponentType, InspectionStatus
from app.schemas.digital_twin import DigitalTwinJSON, PanelComponent, PanelMetadata
from app.schemas.state_machine import (
    ExportSignOffError,
    InspectionStateMachine,
    SignOffCredentials,
    StateTransitionError,
)


def _sample_twin(low_conf_verified: bool = True) -> DigitalTwinJSON:
    return DigitalTwinJSON(
        project_id=uuid4(),
        inspection_id=uuid4(),
        panel=PanelMetadata(panel_id="Q1", name="Quadro Teste"),
        components=[
            PanelComponent(
                component_id="DJ-1",
                label="DJ1",
                component_type=ComponentType.DISJUNTOR_CIRCUITO,
                detection_confidence=0.62,  # < 0.80 -> requires_human_review=True
                verified_by_human=low_conf_verified,
            )
        ],
    )


def test_blocks_direct_draft_to_validated_or_exported() -> None:
    with pytest.raises(StateTransitionError):
        InspectionStateMachine.assert_transition(
            InspectionStatus.DRAFT, InspectionStatus.ENGINEER_VALIDATED
        )

    with pytest.raises(StateTransitionError):
        InspectionStateMachine.assert_transition(
            InspectionStatus.DRAFT, InspectionStatus.EXPORTED
        )


def test_blocks_sign_off_when_low_confidence_components_unverified() -> None:
    twin = _sample_twin(low_conf_verified=False)
    creds = SignOffCredentials(
        engineer_name="Eng. Maria Silva",
        engineer_crea="CREA-SP 5061234567",
        art_number="28027230251234567",
    )
    with pytest.raises(StateTransitionError, match="low confidence"):
        InspectionStateMachine.validate_for_sign_off(
            current_status=InspectionStatus.AI_PROCESSED,
            digital_twin=twin,
            credentials=creds,
        )


def test_allows_sign_off_and_export_after_human_verification() -> None:
    twin = _sample_twin(low_conf_verified=True)
    creds = SignOffCredentials(
        engineer_name="Eng. Maria Silva",
        engineer_crea="crea-sp 5061234567",
        art_number="ART-2026-0001",
    )
    receipt = InspectionStateMachine.validate_for_sign_off(
        current_status=InspectionStatus.AI_PROCESSED,
        digital_twin=twin,
        credentials=creds,
    )
    assert receipt.new_status == InspectionStatus.ENGINEER_VALIDATED
    assert receipt.engineer_crea == "CREA-SP 5061234567"
    assert len(receipt.digital_twin_sha256) == 64

    verified_hash = InspectionStateMachine.assert_can_export(
        current_status=receipt.new_status,
        digital_twin=twin,
        stored_digital_twin_sha256=receipt.digital_twin_sha256,
        validated_by_crea=receipt.engineer_crea,
    )
    assert verified_hash == receipt.digital_twin_sha256


def test_blocks_export_in_draft_or_ai_processed_or_if_tampered() -> None:
    twin = _sample_twin(low_conf_verified=True)
    digest = twin.canonical_sha256()

    for forbidden_status in (InspectionStatus.DRAFT, InspectionStatus.AI_PROCESSED):
        with pytest.raises(ExportSignOffError, match="Official export forbidden"):
            InspectionStateMachine.assert_can_export(
                current_status=forbidden_status,
                digital_twin=twin,
                stored_digital_twin_sha256=digest,
                validated_by_crea="CREA-SP 12345",
            )

    # Tamper DigitalTwinJSON after sign-off
    tampered = twin.model_copy(deep=True)
    tampered.panel.name = "Quadro Alterado Sem Nova Assinatura"
    with pytest.raises(ExportSignOffError, match="modified after engineer sign-off"):
        InspectionStateMachine.assert_can_export(
            current_status=InspectionStatus.ENGINEER_VALIDATED,
            digital_twin=tampered,
            stored_digital_twin_sha256=digest,
            validated_by_crea="CREA-SP 12345",
        )
