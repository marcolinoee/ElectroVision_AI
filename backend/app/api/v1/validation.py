"""Engineer Sign-Off (CREA/ART) endpoint enforcing the rigid state machine."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.models.inspection import Inspection
from app.schemas.api import SignOffRequest, SignOffResponse
from app.schemas.state_machine import InspectionStateMachine, StateTransitionError

router = APIRouter(tags=["validation"])
DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/inspections/{inspection_id}/sign-off",
    response_model=SignOffResponse,
)
async def sign_off_inspection(
    inspection_id: UUID,
    payload: SignOffRequest,
    db: DbSession,
) -> SignOffResponse:
    """Validate DigitalTwinJSON and transition inspection AI_PROCESSED -> ENGINEER_VALIDATED."""
    inspection = await db.get(Inspection, inspection_id)
    if inspection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection not found.")

    if payload.digital_twin.inspection_id != inspection.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="DigitalTwinJSON.inspection_id does not match URL inspection_id.",
        )

    try:
        receipt = InspectionStateMachine.validate_for_sign_off(
            current_status=inspection.status,
            digital_twin=payload.digital_twin,
            credentials=payload.credentials,
        )
    except StateTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    inspection.digital_twin_json = payload.digital_twin.model_dump(mode="json")
    inspection.digital_twin_sha256 = receipt.digital_twin_sha256
    inspection.status = receipt.new_status
    inspection.validated_by_name = receipt.engineer_name
    inspection.validated_by_crea = receipt.engineer_crea
    inspection.art_number = receipt.art_number
    inspection.validated_at = receipt.validated_at

    audit = AuditLog(
        project_id=inspection.project_id,
        inspection_id=inspection.id,
        event_type="ENGINEER_SIGN_OFF",
        actor_name=receipt.engineer_name,
        actor_crea=receipt.engineer_crea,
        art_number=receipt.art_number,
        previous_status=receipt.previous_status,
        new_status=receipt.new_status,
        digital_twin_sha256=receipt.digital_twin_sha256,
        details_json={"components_count": len(payload.digital_twin.components)},
    )
    db.add(audit)
    await db.flush()

    return SignOffResponse(
        inspection_id=inspection.id,
        status=inspection.status,
        digital_twin_sha256=receipt.digital_twin_sha256,
        validated_by_name=receipt.engineer_name,
        validated_by_crea=receipt.engineer_crea,
        art_number=receipt.art_number,
        validated_at=receipt.validated_at,
    )
