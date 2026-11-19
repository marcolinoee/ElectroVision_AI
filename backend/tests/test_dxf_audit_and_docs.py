"""Tests for Phase 3 CAD Engine (ezdxf.audit), Memorial DOCX, Retrofit XLSX, SHA-256 Signer & Export API."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import docx
import ezdxf
import openpyxl
import pytest
from httpx import AsyncClient

from app.models.enums import (
    ArtifactType,
    ComponentType,
    GroundingScheme,
    InspectionStatus,
    SupplySystem,
    TripCurve,
)
from app.schemas.digital_twin import (
    CircuitSpec,
    DigitalTwinJSON,
    PanelComponent,
    PanelMetadata,
    SpatialCalibration,
)
from app.schemas.state_machine import ExportSignOffError
from app.services.cad_engine.planta_overlay_dxf import (
    PlantaOverlayPreconditionError,
    generate_planta_overlay_dxf,
)
from app.services.cad_engine.unifilar_dxf import generate_unifilar_dxf_and_svg
from app.services.doc_engine.export_pipeline import run_signed_export_package
from app.services.doc_engine.sha256_signer import verify_export_manifest


def _sample_twin(calibration: SpatialCalibration | None = None) -> DigitalTwinJSON:
    return DigitalTwinJSON(
        project_id=uuid4(),
        inspection_id=uuid4(),
        panel=PanelMetadata(
            panel_id="QDC-01",
            name="Quadro Geral Teste",
            supply_system=SupplySystem.BIFASICO_127_220V,
            grounding_scheme=GroundingScheme.TN_S,
            nominal_voltage_v=220.0,
            main_breaker_id="DJ-GERAL",
            has_idr=True,
            has_dps=False,  # Triggers DPS finding for SINAPI budget test
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
            ),
            PanelComponent(
                component_id="IDR-01",
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
                rated_current_a=16.0,
                trip_curve=TripCurve.B,
            ),
        ],
        circuits=[
            CircuitSpec(
                circuit_id="C1",
                name="Iluminação Sala",
                circuit_kind="ILUMINACAO",
                phase_allocation="F1",
                voltage_v=127.0,
                load_power_va=1000.0,
                length_m=15.0,
                breaker_component_id="DJ-C1",
                idr_component_id="IDR-01",
                cable_phase_mm2=1.5,
                plan_x_m=4.5,
                plan_y_m=3.2,
            )
        ],
        spatial_calibration=calibration,
    )


def _create_base_architectural_dxf(path: Path) -> Path:
    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (10, 0), (10, 8), (0, 8), (0, 0)])
    doc.saveas(str(path))
    return path


def test_unifilar_dxf_passes_ezdxf_audit_and_generates_svg(tmp_path: Path) -> None:
    twin = _sample_twin()
    res = generate_unifilar_dxf_and_svg(
        digital_twin=twin,
        dxf_destination=tmp_path / "unifilar.dxf",
        svg_destination=tmp_path / "unifilar.svg",
        engineer_name="Eng. Ana Costa",
        engineer_crea="CREA-SP 5060001111",
        art_number="ART-2026-100",
        base_dir=tmp_path,
    )
    assert res.dxf_audit.passed is True
    assert res.dxf_audit.error_count == 0
    assert res.dxf_path.exists()
    assert res.svg_path.exists()

    # Reload generated DXF and re-audit independently
    reloaded = ezdxf.readfile(str(res.dxf_path))
    auditor = reloaded.audit()
    assert len(auditor.errors) == 0

    svg_text = res.svg_path.read_text(encoding="utf-8")
    assert "<svg" in svg_text
    assert twin.canonical_sha256() in svg_text
    assert "CREA-SP 5060001111" in svg_text


def test_planta_overlay_dxf_requires_base_dxf_and_human_calibration(tmp_path: Path) -> None:
    # 1. Fails without spatial_calibration
    with pytest.raises(PlantaOverlayPreconditionError, match="SpatialCalibration"):
        generate_planta_overlay_dxf(_sample_twin(None), tmp_path / "planta.dxf", base_dir=tmp_path)

    base_dxf = _create_base_architectural_dxf(tmp_path / "arq_base.dxf")

    # 2. Fails when calibrated_by_human=False
    uncalibrated = SpatialCalibration(
        base_dxf_path=str(base_dxf),
        origin_x=1.0,
        origin_y=1.0,
        scale_px_per_meter=50.0,
        calibrated_by_human=False,
    )
    with pytest.raises(PlantaOverlayPreconditionError, match="confirmed by the engineer"):
        generate_planta_overlay_dxf(
            _sample_twin(uncalibrated), tmp_path / "planta.dxf", base_dir=tmp_path
        )

    # 3. Succeeds when calibrated_by_human=True over existing base DXF & passes ezdxf.audit()
    calibrated = uncalibrated.model_copy(update={"calibrated_by_human": True})
    out = generate_planta_overlay_dxf(
        _sample_twin(calibrated), tmp_path / "planta_ok.dxf", base_dir=tmp_path
    )
    assert out.dxf_audit.passed is True
    assert out.placed_points == 1
    reloaded = ezdxf.readfile(str(out.dxf_path))
    assert "EV_ELETRICA_QUADRO" in reloaded.layers
    assert len(reloaded.audit().errors) == 0


def test_signed_export_package_blocks_unsigned_and_verifies_sha256_manifest(tmp_path: Path) -> None:
    base_dxf = _create_base_architectural_dxf(tmp_path / "arq.dxf")
    twin = _sample_twin(
        SpatialCalibration(
            base_dxf_path=str(base_dxf),
            origin_x=0.5,
            origin_y=0.5,
            scale_px_per_meter=100.0,
            calibrated_by_human=True,
        )
    )
    digest = twin.canonical_sha256()

    # Forbidden before ENGINEER_VALIDATED
    with pytest.raises(ExportSignOffError):
        run_signed_export_package(
            inspection_status=InspectionStatus.AI_PROCESSED,
            digital_twin=twin,
            stored_digital_twin_sha256=digest,
            engineer_name="Eng. Ana Costa",
            engineer_crea="CREA-SP 5060001111",
            art_number="ART-2026-200",
            requested_artifacts=[ArtifactType.UNIFILAR_DXF],
            export_dir=tmp_path / "exp_blocked",
            base_dir=tmp_path,
        )

    # Succeeds in ENGINEER_VALIDATED
    pkg = run_signed_export_package(
        inspection_status=InspectionStatus.ENGINEER_VALIDATED,
        digital_twin=twin,
        stored_digital_twin_sha256=digest,
        engineer_name="Eng. Ana Costa",
        engineer_crea="CREA-SP 5060001111",
        art_number="ART-2026-200",
        requested_artifacts=[
            ArtifactType.UNIFILAR_DXF,
            ArtifactType.UNIFILAR_SVG,
            ArtifactType.PLANTA_DXF,
            ArtifactType.MEMORIAL_DOCX,
            ArtifactType.RETROFIT_XLSX,
        ],
        export_dir=tmp_path / "exp_ok",
        base_dir=tmp_path,
    )
    assert len(pkg.artifacts) == 5
    ok, errors = verify_export_manifest(pkg.manifest_path)
    assert ok is True
    assert errors == []

    # Verify DOCX contents
    docx_file = tmp_path / "exp_ok" / "memorial_laudo_tecnico.docx"
    loaded_doc = docx.Document(str(docx_file))
    full_text = "\n".join(p.text for p in loaded_doc.paragraphs)
    assert digest in full_text
    assert "CREA-SP 5060001111" in full_text

    # Verify XLSX contents & Excel formula
    xlsx_file = tmp_path / "exp_ok" / "quadro_cargas_retrofit_sinapi.xlsx"
    wb = openpyxl.load_workbook(str(xlsx_file), data_only=False)
    assert wb.sheetnames == ["Quadro_de_Cargas", "Nao_Conformidades", "Orcamento_Retrofit_SINAPI"]
    budget_ws = wb["Orcamento_Retrofit_SINAPI"]
    formulas = [str(cell.value) for row in budget_ws.iter_rows() for cell in row if cell.value]
    assert any(val.startswith("=SUM(") for val in formulas)

    # Tamper one exported artifact -> manifest verification MUST detect mismatch
    svg_file = tmp_path / "exp_ok" / "diagrama_unifilar.svg"
    svg_file.write_text("<!-- tampered -->", encoding="utf-8")
    ok_after_tamper, tamper_errors = verify_export_manifest(pkg.manifest_path)
    assert ok_after_tamper is False
    assert any("SHA-256 mismatch" in err for err in tamper_errors)


async def test_export_api_blocks_unsigned_inspection_with_403(api_client: AsyncClient) -> None:
    proj = await api_client.post(
        "/api/v1/projects",
        json={"name": "Proj Export", "client_name": "Cliente"},
    )
    insp = await api_client.post(
        "/api/v1/inspections",
        json={"project_id": proj.json()["id"], "title": "QDC"},
    )
    resp = await api_client.post(
        f"/api/v1/inspections/{insp.json()['id']}/export",
        json={"artifacts": ["UNIFILAR_DXF", "MEMORIAL_DOCX"]},
    )
    assert resp.status_code == 403
