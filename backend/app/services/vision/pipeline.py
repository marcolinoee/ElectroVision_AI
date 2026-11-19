"""End-to-end Computer Vision inference pipeline & Celery task (vision_queue)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import cv2
import numpy as np

from app.core.celery_app import celery_app
from app.core.config import Settings, get_settings
from app.core.database import build_sync_session_factory
from app.core.logging import get_logger
from app.core.security import compute_sha256_file
from app.core.sse import publish_job_event
from app.models.audit_log import AuditLog
from app.models.component import Component
from app.models.enums import ComponentType, InspectionStatus
from app.models.inspection import Inspection
from app.schemas.digital_twin import (
    CableSpec,
    DigitalTwinJSON,
    PanelComponent,
    PanelMetadata,
)
from app.schemas.state_machine import InspectionStateMachine
from app.services.vision.color_analyzer import classify_cable_color
from app.services.vision.keyframe_extractor import extract_sharp_keyframes
from app.services.vision.ocr_reader import ElectricalOCRReader
from app.services.vision.preprocessor import preprocess_panel_image
from app.services.vision.proxy_gen import generate_image_proxies
from app.services.vision.yolo_detector import DetectorProtocol, UltralyticsYOLODetector

logger = get_logger(__name__)

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
_OCR_TARGET_TYPES = {
    ComponentType.DISJUNTOR_GERAL,
    ComponentType.DISJUNTOR_CIRCUITO,
    ComponentType.IDR,
    ComponentType.DPS,
    ComponentType.CONTATOR,
    ComponentType.RELE_TERMICO,
    ComponentType.MEDIDOR,
}
_CABLE_TYPES = {
    ComponentType.CABO_FASE,
    ComponentType.CABO_NEUTRO,
    ComponentType.CABO_TERRA,
}
_CABLE_ROLE_MAP = {
    ComponentType.CABO_FASE: "FASE",
    ComponentType.CABO_NEUTRO: "NEUTRO",
    ComponentType.CABO_TERRA: "TERRA_PE",
}


@dataclass(frozen=True, slots=True)
class VisionPipelineOutput:
    """Structured output from running the complete vision pipeline on an inspection."""

    digital_twin: DigitalTwinJSON
    proxy_path: Path
    thumbnail_path: Path
    selected_frame_path: Path
    deskew_angle_deg: float
    white_balance_gains: tuple[float, float, float]
    total_components: int
    pending_review_count: int


def _crop_normalized(image_bgr: np.ndarray, x: float, y: float, w: float, h: float) -> np.ndarray:
    img_h, img_w = image_bgr.shape[:2]
    x1 = max(0, min(img_w - 1, int(x * img_w)))
    y1 = max(0, min(img_h - 1, int(y * img_h)))
    x2 = max(x1 + 1, min(img_w, int((x + w) * img_w)))
    y2 = max(y1 + 1, min(img_h, int((y + h) * img_h)))
    return image_bgr[y1:y2, x1:x2]


def run_vision_inference_pipeline(
    project_id: UUID,
    inspection_id: UUID,
    media_path: Path,
    detector: DetectorProtocol,
    ocr_reader: ElectricalOCRReader,
    settings: Settings | None = None,
    panel_name: str = "QDC Inspecionado",
) -> VisionPipelineOutput:
    """Execute deterministic preprocessing -> YOLO -> OCR -> Cable Color -> DigitalTwinJSON."""
    cfg = settings or get_settings()
    cfg.ensure_storage_directories()

    if not media_path.exists():
        raise FileNotFoundError(f"Source inspection media not found: {media_path}")

    # 1. Extract sharp keyframe if input is video
    if media_path.suffix.lower() in _VIDEO_EXTENSIONS:
        frames_dir = cfg.frames_dir / str(inspection_id)
        keyframes = extract_sharp_keyframes(
            video_path=media_path,
            output_dir=frames_dir,
            base_dir=cfg.storage_root,
        )
        selected_frame_path = keyframes[0].file_path
    else:
        selected_frame_path = media_path

    # 2. Generate web proxy & thumbnail atomically
    proxy_artifacts = generate_image_proxies(
        source_image_path=selected_frame_path,
        output_dir=cfg.proxies_dir / str(inspection_id),
        stem=str(inspection_id),
        base_dir=cfg.storage_root,
    )

    # 3. Load frame and apply mandatory color constancy + deskew BEFORE OCR & color analysis
    raw_bgr = cv2.imread(str(selected_frame_path))
    if raw_bgr is None:
        raise ValueError(f"Failed to decode image for vision pipeline: {selected_frame_path}")

    preprocessed = preprocess_panel_image(raw_bgr)
    image_bgr = preprocessed.image_bgr

    # 4. Run YOLO detection
    detections = detector.detect(image_bgr)

    # 5. Enrich each detection with OCR or Cable Color Analysis
    panel_components: list[PanelComponent] = []
    main_breaker_id: str | None = None
    has_idr = False
    has_dps = False
    has_pe_busbar = False
    has_neutral_busbar = False

    for idx, det in enumerate(detections, start=1):
        comp_id = f"COMP-{idx:03d}"
        crop = _crop_normalized(image_bgr, det.bbox.x, det.bbox.y, det.bbox.w, det.bbox.h)

        ocr_reading = None
        trip_curve = None
        rated_current_a = None
        sensitivity_ma = None
        breaking_capacity_ka = None
        dps_class = None
        dps_uc_v = None
        dps_imax_ka = None
        cable_spec = None

        if det.component_type in _OCR_TARGET_TYPES:
            ocr_reading, parsed = ocr_reader.read_component_crop(crop)
            trip_curve = parsed.trip_curve
            rated_current_a = parsed.rated_current_a
            sensitivity_ma = parsed.sensitivity_ma
            breaking_capacity_ka = parsed.breaking_capacity_ka
            if det.component_type == ComponentType.DPS:
                dps_class = parsed.dps_class  # type: ignore[assignment]
                dps_uc_v = parsed.voltage_v
                dps_imax_ka = parsed.breaking_capacity_ka

        if det.component_type in _CABLE_TYPES:
            color_res = classify_cable_color(
                crop, confidence_threshold=cfg.electrovision_confidence_threshold
            )
            cable_spec = CableSpec(
                conductor_role=_CABLE_ROLE_MAP[det.component_type],  # type: ignore[arg-type]
                color=color_res.color,
                color_confidence=color_res.confidence,
                requires_human_review=color_res.requires_human_review,
            )

        if det.component_type == ComponentType.DISJUNTOR_GERAL and main_breaker_id is None:
            main_breaker_id = comp_id
        elif det.component_type == ComponentType.IDR:
            has_idr = True
        elif det.component_type == ComponentType.DPS:
            has_dps = True
        elif det.component_type == ComponentType.BARRAMENTO_TERRA:
            has_pe_busbar = True
        elif det.component_type == ComponentType.BARRAMENTO_NEUTRO:
            has_neutral_busbar = True

        panel_components.append(
            PanelComponent(
                component_id=comp_id,
                label=f"{det.component_type.value[:4]}-{idx}",
                component_type=det.component_type,
                rated_current_a=rated_current_a,
                trip_curve=trip_curve,
                breaking_capacity_ka=breaking_capacity_ka,
                sensitivity_ma=sensitivity_ma,
                dps_class=dps_class,
                dps_uc_v=dps_uc_v,
                dps_imax_ka=dps_imax_ka,
                cable_spec=cable_spec,
                bbox=det.bbox,
                detection_confidence=det.confidence,
                ocr_reading=ocr_reading,
                requires_human_review=det.requires_human_review,
                verified_by_human=False,
            )
        )

    digital_twin = DigitalTwinJSON(
        project_id=project_id,
        inspection_id=inspection_id,
        panel=PanelMetadata(
            panel_id=f"QDC-{str(inspection_id)[:8].upper()}",
            name=panel_name,
            main_breaker_id=main_breaker_id,
            has_idr=has_idr,
            has_dps=has_dps,
            has_pe_busbar=has_pe_busbar,
            has_neutral_busbar=has_neutral_busbar,
        ),
        components=panel_components,
        source_image_sha256=compute_sha256_file(selected_frame_path),
    )

    return VisionPipelineOutput(
        digital_twin=digital_twin,
        proxy_path=proxy_artifacts.proxy_path,
        thumbnail_path=proxy_artifacts.thumbnail_path,
        selected_frame_path=selected_frame_path,
        deskew_angle_deg=preprocessed.deskew_angle_deg,
        white_balance_gains=preprocessed.white_balance_gains,
        total_components=len(panel_components),
        pending_review_count=len(digital_twin.pending_review_components()),
    )


@celery_app.task(name="app.services.vision.pipeline.run_inspection_vision_task", bind=True)
def run_inspection_vision_task(self: Any, inspection_id: str) -> dict[str, Any]:
    """Celery task executed on isolated `worker-ml` (`vision_queue`)."""
    job_id = str(self.request.id or inspection_id)
    settings = get_settings()
    session_factory = build_sync_session_factory()

    publish_job_event(job_id, "STARTED", 5, "Iniciando pipeline de Visão Computacional...")

    with session_factory() as session:
        inspection = session.get(Inspection, UUID(inspection_id))
        if inspection is None:
            publish_job_event(job_id, "FAILED", 100, "Inspeção não encontrada.")
            raise ValueError(f"Inspection {inspection_id} not found.")

        if not inspection.source_media_path:
            publish_job_event(job_id, "FAILED", 100, "Mídia de origem não enviada.")
            raise ValueError(f"Inspection {inspection_id} has no uploaded source media.")

        try:
            InspectionStateMachine.assert_transition(
                inspection.status, InspectionStatus.AI_PROCESSED
            )

            publish_job_event(
                job_id, "PROGRESS", 25, "Pré-processando (constância de cor + deskew) e carregando YOLO..."
            )
            active_weights = settings.models_weights_dir / "active.pt"
            detector = UltralyticsYOLODetector(
                weights_path=active_weights,
                device=settings.electrovision_device,
                review_threshold=settings.electrovision_confidence_threshold,
            )
            ocr_reader = ElectricalOCRReader(
                use_gpu=settings.electrovision_device == "cuda",
                confidence_threshold=settings.electrovision_confidence_threshold,
            )

            publish_job_event(job_id, "PROGRESS", 55, "Executando detecção YOLO, OCR e análise de cores...")
            result = run_vision_inference_pipeline(
                project_id=inspection.project_id,
                inspection_id=inspection.id,
                media_path=Path(inspection.source_media_path),
                detector=detector,
                ocr_reader=ocr_reader,
                settings=settings,
                panel_name=inspection.title,
            )

            publish_job_event(job_id, "PROGRESS", 85, "Persistindo DigitalTwinJSON e componentes...")
            previous_status = inspection.status
            inspection.proxy_media_path = str(result.proxy_path)
            inspection.digital_twin_json = result.digital_twin.model_dump(mode="json")
            inspection.status = InspectionStatus.AI_PROCESSED

            # Replace relational Component projection atomically inside transaction
            inspection.components.clear()
            for comp in result.digital_twin.components:
                inspection.components.append(
                    Component(
                        inspection_id=inspection.id,
                        label_code=comp.label,
                        component_type=comp.component_type,
                        rated_current_a=comp.rated_current_a,
                        trip_curve=comp.trip_curve,
                        breaking_capacity_ka=comp.breaking_capacity_ka,
                        poles=comp.poles,
                        sensitivity_ma=comp.sensitivity_ma,
                        cable_section_mm2=comp.cable_spec.section_mm2 if comp.cable_spec else None,
                        cable_color=comp.cable_spec.color if comp.cable_spec else None,
                        bbox_x=comp.bbox.x if comp.bbox else None,
                        bbox_y=comp.bbox.y if comp.bbox else None,
                        bbox_w=comp.bbox.w if comp.bbox else None,
                        bbox_h=comp.bbox.h if comp.bbox else None,
                        detection_confidence=comp.detection_confidence,
                        ocr_text=comp.ocr_reading.raw_text if comp.ocr_reading else None,
                        ocr_confidence=comp.ocr_reading.confidence if comp.ocr_reading else None,
                        requires_human_review=comp.requires_human_review,
                        verified_by_human=comp.verified_by_human,
                    )
                )

            session.add(
                AuditLog(
                    project_id=inspection.project_id,
                    inspection_id=inspection.id,
                    event_type="AI_VISION_PROCESSED",
                    previous_status=previous_status,
                    new_status=InspectionStatus.AI_PROCESSED,
                    details_json={
                        "total_components": result.total_components,
                        "pending_review_count": result.pending_review_count,
                        "deskew_angle_deg": result.deskew_angle_deg,
                    },
                )
            )
            session.commit()

            summary = {
                "inspection_id": str(inspection.id),
                "status": InspectionStatus.AI_PROCESSED.value,
                "total_components": result.total_components,
                "pending_review_count": result.pending_review_count,
            }
            publish_job_event(job_id, "COMPLETED", 100, "Inferência concluída com sucesso.", summary)
            return summary
        except Exception as exc:
            session.rollback()
            logger.exception("vision_inference_failed", inspection_id=inspection_id, error=str(exc))
            publish_job_event(job_id, "FAILED", 100, f"Erro na inferência: {exc}")
            raise
