"""Tests for idempotent seeds, ABNT copyright compliance, and foundational API endpoints."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ComponentType, InspectionStatus
from app.models.inspection import Inspection
from app.models.rule_metadata import RuleMetadata
from app.models.sinapi_item import SinapiItem
from app.schemas.digital_twin import DigitalTwinJSON, PanelComponent, PanelMetadata
from app.seeds.rule_metadata_seed import RULE_METADATA_SEED, seed_rule_metadata
from app.seeds.sinapi_eletrica_seed import SINAPI_ELETRICA_SEED, seed_sinapi_items


async def test_seeds_are_idempotent_and_copyright_safe(db_session: AsyncSession) -> None:
    inserted_rules_1 = await seed_rule_metadata(db_session)
    inserted_sinapi_1 = await seed_sinapi_items(db_session)
    await db_session.commit()

    assert inserted_rules_1 == len(RULE_METADATA_SEED)
    assert inserted_sinapi_1 == len(SINAPI_ELETRICA_SEED)

    # Re-running seeds must insert 0 duplicates
    inserted_rules_2 = await seed_rule_metadata(db_session)
    inserted_sinapi_2 = await seed_sinapi_items(db_session)
    await db_session.commit()

    assert inserted_rules_2 == 0
    assert inserted_sinapi_2 == 0

    rule_count = await db_session.scalar(select(func.count(RuleMetadata.id)))
    sinapi_count = await db_session.scalar(select(func.count(SinapiItem.id)))
    assert rule_count == len(RULE_METADATA_SEED)
    assert sinapi_count == len(SINAPI_ELETRICA_SEED)

    # Copyright guardrail: concise structured metadata only, no full verbatim ABNT prose blocks
    for rule in RULE_METADATA_SEED:
        assert len(rule["check_summary"]) < 400
        assert isinstance(rule["parameters_json"], dict)
        assert len(rule["parameters_json"]) > 0


async def test_api_health_project_inspection_and_sign_off_flow(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    health = await api_client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    # 1. Create Project
    proj_resp = await api_client.post(
        "/api/v1/projects",
        json={
            "name": "Retrofit QDC Edifício Paulista",
            "client_name": "Condomínio Paulista",
            "supply_system": "TRIFASICO_220_127V",
            "grounding_scheme": "TN_S",
            "nominal_voltage_v": 220.0,
        },
    )
    assert proj_resp.status_code == 201
    project_id = proj_resp.json()["id"]

    # 2. Create Inspection (starts in DRAFT)
    insp_resp = await api_client.post(
        "/api/v1/inspections",
        json={"project_id": project_id, "title": "Inspeção QDC-01"},
    )
    assert insp_resp.status_code == 201
    inspection_id = insp_resp.json()["id"]
    assert insp_resp.json()["status"] == "DRAFT"

    twin = DigitalTwinJSON(
        project_id=project_id,
        inspection_id=inspection_id,
        panel=PanelMetadata(panel_id="QDC-01", name="Quadro 01"),
        components=[
            PanelComponent(
                component_id="DJ-1",
                label="DJ1",
                component_type=ComponentType.DISJUNTOR_GERAL,
                detection_confidence=0.95,
            )
        ],
    )

    # 3. Attempting Sign-Off while in DRAFT must fail with 409 Conflict
    sign_off_draft = await api_client.post(
        f"/api/v1/inspections/{inspection_id}/sign-off",
        json={
            "credentials": {
                "engineer_name": "Eng. Carlos Souza",
                "engineer_crea": "CREA-SP 5069999999",
                "art_number": "ART-2026-9999",
            },
            "digital_twin": twin.model_dump(mode="json"),
        },
    )
    assert sign_off_draft.status_code == 409

    # 4. Simulate Worker ML transitioning inspection to AI_PROCESSED
    insp_obj = await db_session.get(Inspection, twin.inspection_id)
    assert insp_obj is not None
    insp_obj.status = InspectionStatus.AI_PROCESSED
    await db_session.commit()

    # 5. Sign-Off now succeeds and produces deterministic SHA-256
    sign_off_ok = await api_client.post(
        f"/api/v1/inspections/{inspection_id}/sign-off",
        json={
            "credentials": {
                "engineer_name": "Eng. Carlos Souza",
                "engineer_crea": "CREA-SP 5069999999",
                "art_number": "ART-2026-9999",
            },
            "digital_twin": twin.model_dump(mode="json"),
        },
    )
    assert sign_off_ok.status_code == 200
    body = sign_off_ok.json()
    assert body["status"] == "ENGINEER_VALIDATED"
    assert body["digital_twin_sha256"] == twin.canonical_sha256()
