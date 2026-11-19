"""Official Engineering Export Orchestrator & Celery Task (`engine_queue`).

HARD GUARDRAIL:
Calls `InspectionStateMachine.assert_can_export(...)` BEFORE generating any official artifact.
Exports are strictly forbidden without CREA Sign-Off and intact DigitalTwinJSON SHA-256.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.celery_app import celery_app
from app.core.config import Settings, get_settings
from app.core.database import build_sync_session_factory
from app.core.logging import get_logger
from app.core.sse import publish_job_event
from app.models.audit_log import AuditLog
from app.models.enums import ArtifactType, InspectionStatus
from app.models.inspection import Inspection
from app.models.project import Project
from app.models.sinapi_item import SinapiItem
from app.schemas.digital_twin import DigitalTwinJSON
from app.schemas.state_machine import InspectionStateMachine
from app.services.cad_engine.planta_overlay_dxf import generate_planta_overlay_dxf
from app.services.cad_engine.unifilar_dxf import generate_unifilar_dxf_and_svg
from app.services.compliance.deterministic_engine import (
    ComplianceReport,
    evaluate_digital_twin_compliance,
)
from app.services.doc_engine.memorial_docx import generate_memorial_docx
from app.services.doc_engine.retrofit_xlsx import generate_retrofit_xlsx
from app.services.doc_engine.sha256_signer import SignedArtifactRecord, write_export_audit_manifest

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ExportPackageResult:
    export_dir: Path
    manifest_path: Path
    digital_twin_sha256: str
    compliance_report: ComplianceReport
    artifacts: list[SignedArtifactRecord]


def run_signed_export_package(
    inspection_status: InspectionStatus,
    digital_twin: DigitalTwinJSON,
    stored_digital_twin_sha256: str | None,
    engineer_name: str,
    engineer_crea: str | None,
    art_number: str | None,
    requested_artifacts: list[ArtifactType],
    export_dir: Path,
    project_name: str = "Projeto Elétrico",
    client_name: str = "Cliente",
    sinapi_catalog: list[dict[str, Any]] | None = None,
    base_dir: Path | None = None,
) -> ExportPackageResult:
    """Enforce CREA/ART Sign-Off, run deterministic compliance, generate CAD/Docs, and sign SHA-256."""
    verified_sha = InspectionStateMachine.assert_can_export(
        current_status=inspection_status,
        digital_twin=digital_twin,
        stored_digital_twin_sha256=stored_digital_twin_sha256,
        validated_by_crea=engineer_crea,
    )
    assert engineer_crea is not None

    export_dir.mkdir(parents=True, exist_ok=True)
    compliance_report = evaluate_digital_twin_compliance(digital_twin)

    generated: list[tuple[ArtifactType, Path]] = []
    req_set = set(requested_artifacts)

    if ArtifactType.UNIFILAR_DXF in req_set or ArtifactType.UNIFILAR_SVG in req_set:
        unifilar_res = generate_unifilar_dxf_and_svg(
            digital_twin=digital_twin,
            dxf_destination=export_dir / "diagrama_unifilar.dxf",
            svg_destination=export_dir / "diagrama_unifilar.svg",
            engineer_name=engineer_name,
            engineer_crea=engineer_crea,
            art_number=art_number,
            base_dir=base_dir,
        )
        if ArtifactType.UNIFILAR_DXF in req_set:
            generated.append((ArtifactType.UNIFILAR_DXF, unifilar_res.dxf_path))
        if ArtifactType.UNIFILAR_SVG in req_set:
            generated.append((ArtifactType.UNIFILAR_SVG, unifilar_res.svg_path))

    if ArtifactType.PLANTA_DXF in req_set:
        planta_res = generate_planta_overlay_dxf(
            digital_twin=digital_twin,
            destination=export_dir / "planta_eletrica.dxf",
            base_dir=base_dir,
        )
        generated.append((ArtifactType.PLANTA_DXF, planta_res.dxf_path))

    if ArtifactType.MEMORIAL_DOCX in req_set:
        docx_path = generate_memorial_docx(
            digital_twin=digital_twin,
            compliance_report=compliance_report,
            destination=export_dir / "memorial_laudo_tecnico.docx",
            engineer_name=engineer_name,
            engineer_crea=engineer_crea,
            art_number=art_number,
            project_name=project_name,
            client_name=client_name,
            base_dir=base_dir,
        )
        generated.append((ArtifactType.MEMORIAL_DOCX, docx_path))

    if ArtifactType.RETROFIT_XLSX in req_set:
        xlsx_path = generate_retrofit_xlsx(
            digital_twin=digital_twin,
            compliance_report=compliance_report,
            destination=export_dir / "quadro_cargas_retrofit_sinapi.xlsx",
            engineer_name=engineer_name,
            engineer_crea=engineer_crea,
            art_number=art_number,
            sinapi_catalog=sinapi_catalog,
            base_dir=base_dir,
        )
        generated.append((ArtifactType.RETROFIT_XLSX, xlsx_path))

    manifest_path, signed_records = write_export_audit_manifest(
        export_dir=export_dir,
        inspection_id=str(digital_twin.inspection_id),
        digital_twin_sha256=verified_sha,
        engineer_name=engineer_name,
        engineer_crea=engineer_crea,
        art_number=art_number,
        artifacts=generated,
        base_dir=base_dir,
    )

    return ExportPackageResult(
        export_dir=export_dir,
        manifest_path=manifest_path,
        digital_twin_sha256=verified_sha,
        compliance_report=compliance_report,
        artifacts=signed_records,
    )


@celery_app.task(name="app.services.doc_engine.export_pipeline.run_official_export_task", bind=True)
def run_official_export_task(
    self: Any,
    inspection_id: str,
    artifact_types: list[str],
) -> dict[str, Any]:
    """Celery task executed on isolated `worker-engine` (`engine_queue`)."""
    job_id = str(self.request.id or inspection_id)
    settings: Settings = get_settings()
    settings.ensure_storage_directories()
    session_factory = build_sync_session_factory()

    publish_job_event(job_id, "STARTED", 10, "Validando Sign-Off CREA/ART e integridade SHA-256...")

    with session_factory() as session:
        inspection = session.get(Inspection, UUID(inspection_id))
        if inspection is None:
            publish_job_event(job_id, "FAILED", 100, "Inspeção não encontrada.")
            raise ValueError(f"Inspection {inspection_id} not found.")

        project = session.get(Project, inspection.project_id)
        try:
            if not inspection.digital_twin_json:
                raise ValueError("DigitalTwinJSON ausente na inspeção.")
            twin = DigitalTwinJSON.model_validate(inspection.digital_twin_json)

            sinapi_rows = list(session.scalars(select(SinapiItem)).all())
            sinapi_catalog = [
                {
                    "sinapi_code": row.sinapi_code,
                    "description": row.description,
                    "unit": row.unit,
                    "category": row.category,
                    "unit_price_brl": row.unit_price_brl,
                }
                for row in sinapi_rows
            ] or None

            publish_job_event(job_id, "PROGRESS", 45, "Gerando CAD (.DXF/.SVG) auditado e documentos (.DOCX/.XLSX)...")
            requested = [ArtifactType(a) for a in artifact_types]
            export_dir = settings.exports_dir / str(inspection.id)

            pkg = run_signed_export_package(
                inspection_status=inspection.status,
                digital_twin=twin,
                stored_digital_twin_sha256=inspection.digital_twin_sha256,
                engineer_name=inspection.validated_by_name or "Engenheiro",
                engineer_crea=inspection.validated_by_crea,
                art_number=inspection.art_number,
                requested_artifacts=requested,
                export_dir=export_dir,
                project_name=project.name if project else "Projeto Elétrico",
                client_name=project.client_name if project else "Cliente",
                sinapi_catalog=sinapi_catalog,
                base_dir=settings.storage_root,
            )

            publish_job_event(job_id, "PROGRESS", 85, "Registrando trilha de auditoria SHA-256...")
            previous_status = inspection.status
            inspection.status = InspectionStatus.EXPORTED
            inspection.exported_at = datetime.now(UTC)
            inspection.compliance_summary = pkg.compliance_report.model_dump(mode="json")

            for rec in pkg.artifacts:
                session.add(
                    AuditLog(
                        project_id=inspection.project_id,
                        inspection_id=inspection.id,
                        event_type="ARTIFACT_EXPORTED",
                        actor_name=inspection.validated_by_name,
                        actor_crea=inspection.validated_by_crea,
                        art_number=inspection.art_number,
                        previous_status=previous_status,
                        new_status=InspectionStatus.EXPORTED,
                        digital_twin_sha256=pkg.digital_twin_sha256,
                        artifact_type=rec.artifact_type,
                        artifact_path=str(rec.path),
                        artifact_sha256=rec.sha256,
                        details_json={"size_bytes": rec.size_bytes, "filename": rec.filename},
                    )
                )
            session.commit()

            payload = {
                "inspection_id": str(inspection.id),
                "status": InspectionStatus.EXPORTED.value,
                "digital_twin_sha256": pkg.digital_twin_sha256,
                "manifest_path": str(pkg.manifest_path),
                "artifacts": [
                    {
                        "type": r.artifact_type.value,
                        "filename": r.filename,
                        "sha256": r.sha256,
                    }
                    for r in pkg.artifacts
                ],
            }
            publish_job_event(job_id, "COMPLETED", 100, "Exportação oficial assinada concluída.", payload)
            return payload
        except Exception as exc:
            session.rollback()
            logger.exception("official_export_failed", inspection_id=inspection_id, error=str(exc))
            publish_job_event(job_id, "FAILED", 100, f"Erro na exportação: {exc}")
            raise
