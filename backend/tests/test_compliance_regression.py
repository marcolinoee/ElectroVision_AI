"""Deterministic Compliance Engine regression tests (NBR 5410 / NR-10 / NBR 14039) + local RAG."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import CableColor, ComponentType, GroundingScheme, SupplySystem, TripCurve
from app.models.rule_metadata import NormChunk
from app.schemas.digital_twin import (
    CableSpec,
    CircuitSpec,
    DigitalTwinJSON,
    PanelComponent,
    PanelMetadata,
)
from app.services.compliance.deterministic_engine import evaluate_digital_twin_compliance
from app.services.compliance.norm_rag import LocalONNXEmbedder, search_norm_citations


def _compliant_twin() -> DigitalTwinJSON:
    return DigitalTwinJSON(
        project_id=uuid4(),
        inspection_id=uuid4(),
        panel=PanelMetadata(
            panel_id="QDC-OK",
            name="Quadro Conforme NBR 5410",
            supply_system=SupplySystem.BIFASICO_127_220V,
            grounding_scheme=GroundingScheme.TN_S,
            nominal_voltage_v=220.0,
            main_breaker_id="DJ-GERAL",
            has_idr=True,
            has_dps=True,
            has_pe_busbar=True,
            has_neutral_busbar=True,
            pe_neutral_separated=True,
            door_grounding_present=True,
            warning_sign_nr10_present=True,
            unifilar_diagram_inside_present=True,
        ),
        components=[
            PanelComponent(
                component_id="DJ-GERAL",
                label="Q1",
                component_type=ComponentType.DISJUNTOR_GERAL,
                poles=2,
                rated_current_a=50.0,
                trip_curve=TripCurve.C,
            ),
            PanelComponent(
                component_id="DPS-1",
                label="DPS1",
                component_type=ComponentType.DPS,
                dps_class="II",
                dps_uc_v=275.0,
                dps_imax_ka=45.0,
            ),
            PanelComponent(
                component_id="IDR-1",
                label="IDR1",
                component_type=ComponentType.IDR,
                poles=2,
                rated_current_a=63.0,
                sensitivity_ma=30,
            ),
            PanelComponent(
                component_id="DJ-C1",
                label="C1",
                component_type=ComponentType.DISJUNTOR_CIRCUITO,
                poles=1,
                rated_current_a=10.0,
                trip_curve=TripCurve.B,
            ),
            PanelComponent(
                component_id="DJ-C2",
                label="C2",
                component_type=ComponentType.DISJUNTOR_CIRCUITO,
                poles=1,
                rated_current_a=20.0,
                trip_curve=TripCurve.C,
            ),
        ],
        circuits=[
            CircuitSpec(
                circuit_id="C1",
                name="Iluminação Geral",
                circuit_kind="ILUMINACAO",
                phase_allocation="F1",
                voltage_v=127.0,
                load_power_va=800.0,  # Ib = 6.3A <= In 10A <= Iz 17.5A
                length_m=15.0,
                breaker_component_id="DJ-C1",
                idr_component_id="IDR-1",
                cable_phase_mm2=1.5,
                cable_neutral_mm2=1.5,
                cable_pe_mm2=1.5,
            ),
            CircuitSpec(
                circuit_id="C2",
                name="Tomadas Banheiro",
                circuit_kind="TOMADAS_USO_GERAL",
                phase_allocation="F2",
                voltage_v=127.0,
                load_power_va=1800.0,  # Ib = 14.17A <= In 20A <= Iz 24A
                length_m=12.0,
                is_wet_area=True,
                breaker_component_id="DJ-C2",
                idr_component_id="IDR-1",
                cable_phase_mm2=2.5,
                cable_neutral_mm2=2.5,
                cable_pe_mm2=2.5,
            ),
        ],
    )


def test_compliant_panel_scores_100_percent() -> None:
    report = evaluate_digital_twin_compliance(_compliant_twin())
    assert report.is_compliant is True
    assert report.compliance_score_pct == 100.0
    assert len(report.findings) == 0
    assert len(report.circuit_calculations) == 2
    assert all(c.coordination_ok and c.voltage_drop_ok for c in report.circuit_calculations)


def test_detects_all_major_nbr5410_nr10_and_nbr14039_violations() -> None:
    twin = DigitalTwinJSON(
        project_id=uuid4(),
        inspection_id=uuid4(),
        panel=PanelMetadata(
            panel_id="QDC-FAIL",
            name="Quadro Irregular",
            supply_system=SupplySystem.MEDIA_TENSAO_13_8KV,
            grounding_scheme=GroundingScheme.TN_S,
            nominal_voltage_v=13800.0,
            has_idr=False,
            has_dps=False,
            has_pe_busbar=False,
            has_neutral_busbar=True,
            pe_neutral_separated=False,
            door_grounding_present=False,
            warning_sign_nr10_present=False,
            unifilar_diagram_inside_present=False,
        ),
        components=[
            PanelComponent(
                component_id="DJ-BAD",
                label="DJ1",
                component_type=ComponentType.DISJUNTOR_CIRCUITO,
                poles=1,
                rated_current_a=32.0,  # In = 32A > Iz = 24A for 2.5mm² -> overload violation!
                trip_curve=TripCurve.C,
            ),
            PanelComponent(
                component_id="CAB-WRONG",
                label="F1",
                component_type=ComponentType.CABO_FASE,
                cable_spec=CableSpec(
                    conductor_role="FASE",
                    section_mm2=2.5,
                    color=CableColor.AZUL_CLARO,  # Forbidden color for Phase!
                ),
            ),
        ],
        circuits=[
            CircuitSpec(
                circuit_id="C-WET",
                name="Tomada Externa Longa",
                circuit_kind="TOMADAS_USO_GERAL",
                phase_allocation="F1",
                voltage_v=127.0,
                load_power_va=2000.0,
                length_m=60.0,  # Excessive voltage drop > 4%
                is_wet_area=True,
                is_external_area=True,
                breaker_component_id="DJ-BAD",
                idr_component_id=None,  # Missing IDR 30mA!
                cable_phase_mm2=1.5,  # Undersized (< 2.5mm² for power)
                cable_neutral_color=CableColor.PRETO,  # Wrong neutral color
                cable_pe_color=CableColor.VERMELHO,  # Wrong PE color
            )
        ],
    )
    report = evaluate_digital_twin_compliance(twin)
    rule_codes = {f.rule_code for f in report.findings}

    assert report.is_compliant is False
    assert "NBR5410_DPS_SURGE_PROTECTION" in rule_codes
    assert "NBR5410_SEPARATE_NEUTRAL_PE_BUSBARS" in rule_codes
    assert "NR10_WARNING_SIGN_AND_UNIFILAR" in rule_codes
    assert "NBR14039_MV_PROTECTION_METADATA" in rule_codes
    assert "NBR5410_IDR_30MA_WET_AREAS" in rule_codes
    assert "NBR5410_MIN_SECTION_POWER" in rule_codes
    assert "NBR5410_BREAKER_CABLE_COORDINATION" in rule_codes
    assert "NBR5410_VOLTAGE_DROP_LIMIT" in rule_codes
    assert "NBR5410_CONDUCTOR_COLOR_NEUTRAL_PE" in rule_codes


async def test_local_rag_search_returns_relevant_citations(db_session: AsyncSession) -> None:
    embedder = LocalONNXEmbedder()
    texts = [
        "Proteção diferencial residual IDR 30mA obrigatória em áreas molhadas e banheiros.",
        "Sinalização de segurança NR-10 e prontuário de instalações elétricas.",
    ]
    vecs = embedder.embed_texts(texts, prefix="passage: ")
    for idx, (txt, vec) in enumerate(zip(texts, vecs, strict=True)):
        db_session.add(
            NormChunk(
                standard_code="NBR 5410" if idx == 0 else "NR-10",
                document_filename="user_local_norm.pdf",
                document_sha256="a" * 64,
                page_number=idx + 1,
                chunk_index=idx,
                content=txt,
                embedding=vec,
            )
        )
    await db_session.commit()

    matches = await search_norm_citations(
        db_session,
        query="proteção IDR 30mA áreas molhadas banheiros",
        top_k=2,
        embedder=embedder,
    )
    assert len(matches) == 2
    assert "IDR" in matches[0].excerpt
    assert matches[0].similarity >= matches[1].similarity
