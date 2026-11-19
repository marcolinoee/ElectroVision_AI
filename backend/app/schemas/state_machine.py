"""Rigid CREA/ART Sign-Off State Machine: DRAFT -> AI_PROCESSED -> ENGINEER_VALIDATED -> EXPORTED."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import InspectionStatus
from app.schemas.digital_twin import DigitalTwinJSON


class StateTransitionError(ValueError):
    """Raised when an invalid inspection state transition is attempted."""


class ExportSignOffError(PermissionError):
    """Raised when official report export is attempted without valid Engineer Sign-Off."""


_CREA_PATTERN = re.compile(r"^[A-Z0-9\-\/\s]{4,64}$")


class SignOffCredentials(BaseModel):
    """Mandatory engineer identification for CREA/ART sign-off."""

    model_config = ConfigDict(extra="forbid")

    engineer_name: str = Field(..., min_length=3, max_length=200)
    engineer_crea: str = Field(..., min_length=4, max_length=64)
    art_number: str | None = Field(default=None, min_length=4, max_length=64)

    @field_validator("engineer_crea")
    @classmethod
    def validate_crea_format(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not _CREA_PATTERN.match(normalized):
            raise ValueError(
                "CREA registration must contain 4-64 uppercase alphanumeric, '-', '/', or space characters."
            )
        return normalized


@dataclass(frozen=True, slots=True)
class SignOffReceipt:
    """Immutable receipt produced upon successful ENGINEER_VALIDATED sign-off."""

    previous_status: InspectionStatus
    new_status: InspectionStatus
    digital_twin_sha256: str
    engineer_name: str
    engineer_crea: str
    art_number: str | None
    validated_at: datetime


class InspectionStateMachine:
    """Deterministic state machine enforcing human-in-the-loop CREA/ART sign-off."""

    ALLOWED_TRANSITIONS: dict[InspectionStatus, set[InspectionStatus]] = {
        InspectionStatus.DRAFT: {InspectionStatus.AI_PROCESSED},
        InspectionStatus.AI_PROCESSED: {InspectionStatus.ENGINEER_VALIDATED},
        InspectionStatus.ENGINEER_VALIDATED: {
            InspectionStatus.EXPORTED,
            InspectionStatus.AI_PROCESSED,
        },
        InspectionStatus.EXPORTED: {
            InspectionStatus.EXPORTED,
            InspectionStatus.AI_PROCESSED,
        },
    }

    @classmethod
    def assert_transition(
        cls,
        current: InspectionStatus,
        target: InspectionStatus,
    ) -> None:
        allowed = cls.ALLOWED_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise StateTransitionError(
                f"Invalid state transition: {current.value} -> {target.value}. "
                f"Allowed targets from {current.value}: "
                f"{sorted(s.value for s in allowed)}."
            )

    @classmethod
    def validate_for_sign_off(
        cls,
        current_status: InspectionStatus,
        digital_twin: DigitalTwinJSON,
        credentials: SignOffCredentials,
    ) -> SignOffReceipt:
        """Enforce all preconditions for transitioning AI_PROCESSED -> ENGINEER_VALIDATED."""
        cls.assert_transition(current_status, InspectionStatus.ENGINEER_VALIDATED)

        pending = digital_twin.pending_review_components()
        if pending:
            ids = ", ".join(c.component_id for c in pending)
            raise StateTransitionError(
                f"Cannot sign off inspection: {len(pending)} component(s) with low confidence "
                f"(< 0.80) have not been verified by the engineer: [{ids}]."
            )

        digest = digital_twin.canonical_sha256()
        return SignOffReceipt(
            previous_status=current_status,
            new_status=InspectionStatus.ENGINEER_VALIDATED,
            digital_twin_sha256=digest,
            engineer_name=credentials.engineer_name.strip(),
            engineer_crea=credentials.engineer_crea,
            art_number=credentials.art_number.strip() if credentials.art_number else None,
            validated_at=datetime.now(UTC),
        )

    @classmethod
    def assert_can_export(
        cls,
        current_status: InspectionStatus,
        digital_twin: DigitalTwinJSON | None,
        stored_digital_twin_sha256: str | None,
        validated_by_crea: str | None,
    ) -> str:
        """Hard guardrail blocking official exports (.DXF/.DOCX/.XLSX) without valid Sign-Off.

        Returns the verified SHA-256 digest linking the validated DigitalTwinJSON to artifacts.
        """
        if current_status not in {InspectionStatus.ENGINEER_VALIDATED, InspectionStatus.EXPORTED}:
            raise ExportSignOffError(
                f"Official export forbidden in status '{current_status.value}'. "
                "Inspection must be explicitly signed off (ENGINEER_VALIDATED) by a CREA engineer."
            )

        if not validated_by_crea or not validated_by_crea.strip():
            raise ExportSignOffError(
                "Official export forbidden: missing engineer CREA sign-off record."
            )

        if digital_twin is None or not stored_digital_twin_sha256:
            raise ExportSignOffError(
                "Official export forbidden: missing validated DigitalTwinJSON or SHA-256 signature."
            )

        current_hash = digital_twin.canonical_sha256()
        if current_hash != stored_digital_twin_sha256:
            raise ExportSignOffError(
                "Official export forbidden: DigitalTwinJSON was modified after engineer sign-off "
                f"(expected SHA-256 {stored_digital_twin_sha256}, computed {current_hash}). "
                "Re-validation is required."
            )

        return current_hash
