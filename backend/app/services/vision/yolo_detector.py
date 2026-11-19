"""Local Ultralytics YOLO detector wrapper with canonical electrical class taxonomy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from app.core.logging import get_logger
from app.models.enums import ComponentType
from app.schemas.digital_twin import CONFIDENCE_REVIEW_THRESHOLD, BoundingBox
from app.services.vision.taxonomy import (
    CANONICAL_YOLO_CLASSES,
    COMPONENT_TYPE_TO_YOLO_CLASS_ID,
    CRITICAL_PROTECTION_CLASSES,
)

logger = get_logger(__name__)

__all__ = [
    "CANONICAL_YOLO_CLASSES",
    "COMPONENT_TYPE_TO_YOLO_CLASS_ID",
    "CRITICAL_PROTECTION_CLASSES",
    "DetectorProtocol",
    "RawDetection",
    "UltralyticsYOLODetector",
]


@dataclass(frozen=True, slots=True)
class RawDetection:
    """Single object detection emitted by YOLO before OCR/color enrichment."""

    class_id: int
    component_type: ComponentType
    bbox: BoundingBox
    confidence: float
    requires_human_review: bool


class DetectorProtocol(Protocol):
    """Protocol for YOLO object detector (supports dependency injection in tests)."""

    def detect(self, image_bgr: np.ndarray) -> list[RawDetection]:
        ...


class UltralyticsYOLODetector:
    """Local YOLOv8/v11 detector executing on CPU or explicit CUDA device."""

    def __init__(
        self,
        weights_path: Path,
        device: str = "cpu",
        conf_min: float = 0.25,
        review_threshold: float = CONFIDENCE_REVIEW_THRESHOLD,
    ) -> None:
        self._weights_path = weights_path
        self._device = device
        self._conf_min = conf_min
        self._review_threshold = review_threshold
        self._model: Any | None = None

    def _load_model(self) -> Any:
        if self._model is None:
            if not self._weights_path.exists():
                raise FileNotFoundError(
                    f"YOLO model weights not found at '{self._weights_path}'. "
                    "Place a trained .pt model in storage/models_weights/active.pt."
                )
            from ultralytics import YOLO  # Lazy import isolated to worker-ml

            logger.info(
                "loading_yolo_weights",
                weights=str(self._weights_path),
                device=self._device,
            )
            self._model = YOLO(str(self._weights_path))
        return self._model

    def detect(self, image_bgr: np.ndarray) -> list[RawDetection]:
        model = self._load_model()
        h, w = image_bgr.shape[:2]
        if h <= 0 or w <= 0:
            return []

        results = model.predict(
            source=image_bgr,
            conf=self._conf_min,
            device=self._device,
            verbose=False,
        )
        detections: list[RawDetection] = []
        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls.item())
                conf = float(box.conf.item())
                x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
                nx = max(0.0, min(1.0, x1 / w))
                ny = max(0.0, min(1.0, y1 / h))
                nw = max(1e-4, min(1.0 - nx, (x2 - x1) / w))
                nh = max(1e-4, min(1.0 - ny, (y2 - y1) / h))

                comp_type = CANONICAL_YOLO_CLASSES.get(cls_id, ComponentType.OUTRO)
                detections.append(
                    RawDetection(
                        class_id=cls_id,
                        component_type=comp_type,
                        bbox=BoundingBox(x=round(nx, 6), y=round(ny, 6), w=round(nw, 6), h=round(nh, 6)),
                        confidence=round(conf, 4),
                        requires_human_review=conf < self._review_threshold,
                    )
                )
        return detections
