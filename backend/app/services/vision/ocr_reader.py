"""Local OCR reader (EasyOCR) & deterministic parser for electrical protection faceplates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

import cv2
import numpy as np

from app.core.logging import get_logger
from app.models.enums import TripCurve
from app.schemas.digital_twin import CONFIDENCE_REVIEW_THRESHOLD, OCRReading

logger = get_logger(__name__)

# Deterministic regex patterns for IEC/NBR electrical markings
_CURVE_CURRENT_RE = re.compile(r"\b([BCD])\s*(\d{1,3})\b", re.IGNORECASE)
_CURRENT_AMP_RE = re.compile(r"\b(\d{1,3}(?:[.,]\d)?)\s*A\b", re.IGNORECASE)
_SENSITIVITY_MA_RE = re.compile(r"\b(10|30|100|300|500)\s*mA\b", re.IGNORECASE)
_BREAKING_KA_RE = re.compile(r"\b(\d+(?:[.,]\d)?)\s*kA\b", re.IGNORECASE)
_VOLTAGE_V_RE = re.compile(r"\b(\d{3,4})\s*V\b", re.IGNORECASE)
_SECTION_MM2_RE = re.compile(r"\b(\d+(?:[.,]\d)?)\s*mm[2²]?\b", re.IGNORECASE)
_DPS_CLASS_RE = re.compile(r"\b(?:CLASSE|CLASS|TYPE|TIPO)\s*(I\+II|II|III|I)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ParsedElectricalMarkings:
    """Structured electrical specs extracted from OCR text."""

    trip_curve: TripCurve | None = None
    rated_current_a: float | None = None
    sensitivity_ma: int | None = None
    breaking_capacity_ka: float | None = None
    voltage_v: float | None = None
    cable_section_mm2: float | None = None
    dps_class: str | None = None


def parse_electrical_faceplate_text(raw_text: str) -> ParsedElectricalMarkings:
    """Deterministically parse breaker/IDR/DPS/cable ratings from OCR text."""
    text = raw_text.strip()
    if not text:
        return ParsedElectricalMarkings()

    trip_curve: TripCurve | None = None
    rated_current_a: float | None = None

    curve_match = _CURVE_CURRENT_RE.search(text)
    if curve_match:
        trip_curve = TripCurve(curve_match.group(1).upper())
        rated_current_a = float(curve_match.group(2))
    else:
        amp_match = _CURRENT_AMP_RE.search(text)
        if amp_match:
            rated_current_a = float(amp_match.group(1).replace(",", "."))

    sensitivity_ma: int | None = None
    ma_match = _SENSITIVITY_MA_RE.search(text)
    if ma_match:
        sensitivity_ma = int(ma_match.group(1))

    breaking_ka: float | None = None
    ka_match = _BREAKING_KA_RE.search(text)
    if ka_match:
        breaking_ka = float(ka_match.group(1).replace(",", "."))

    voltage_v: float | None = None
    v_match = _VOLTAGE_V_RE.search(text)
    if v_match:
        voltage_v = float(v_match.group(1))

    section_mm2: float | None = None
    mm_match = _SECTION_MM2_RE.search(text)
    if mm_match:
        section_mm2 = float(mm_match.group(1).replace(",", "."))

    dps_class: str | None = None
    dps_match = _DPS_CLASS_RE.search(text)
    if dps_match:
        dps_class = dps_match.group(1).upper()

    return ParsedElectricalMarkings(
        trip_curve=trip_curve,
        rated_current_a=rated_current_a,
        sensitivity_ma=sensitivity_ma,
        breaking_capacity_ka=breaking_ka,
        voltage_v=voltage_v,
        cable_section_mm2=section_mm2,
        dps_class=dps_class,
    )


class OCRBackendProtocol(Protocol):
    """Protocol for pluggable local OCR engine (EasyOCR in production, fakes in unit tests)."""

    def read_text(self, image_bgr: np.ndarray) -> list[tuple[str, float]]:
        """Return list of (text_fragment, confidence) tuples."""
        ...


class EasyOCRBackend:
    """Lazy-initialized local EasyOCR backend (CPU or CUDA)."""

    def __init__(self, use_gpu: bool = False, languages: list[str] | None = None) -> None:
        self._use_gpu = use_gpu
        self._languages = languages or ["pt", "en"]
        self._reader: Any | None = None

    def _get_reader(self) -> Any:
        if self._reader is None:
            import easyocr  # Imported lazily so api container never requires torch/easyocr

            logger.info("initializing_easyocr", gpu=self._use_gpu, languages=self._languages)
            self._reader = easyocr.Reader(self._languages, gpu=self._use_gpu, verbose=False)
        return self._reader

    def read_text(self, image_bgr: np.ndarray) -> list[tuple[str, float]]:
        reader = self._get_reader()
        # Upscale small breaker faceplates for sharper OCR recognition
        h, w = image_bgr.shape[:2]
        processed = image_bgr
        if min(h, w) < 120:
            processed = cv2.resize(image_bgr, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
        raw_results = reader.readtext(processed, detail=1, paragraph=False)
        return [(str(text).strip(), float(conf)) for (_bbox, text, conf) in raw_results if str(text).strip()]


class ElectricalOCRReader:
    """High-level OCR reader enforcing confidence threshold < 0.80 -> requires_human_review."""

    def __init__(
        self,
        backend: OCRBackendProtocol | None = None,
        use_gpu: bool = False,
        confidence_threshold: float = CONFIDENCE_REVIEW_THRESHOLD,
    ) -> None:
        self._backend: OCRBackendProtocol = backend or EasyOCRBackend(use_gpu=use_gpu)
        self._confidence_threshold = confidence_threshold

    def read_component_crop(
        self, crop_bgr: np.ndarray
    ) -> tuple[OCRReading | None, ParsedElectricalMarkings]:
        if crop_bgr is None or crop_bgr.size == 0:
            return None, ParsedElectricalMarkings()

        fragments = self._backend.read_text(crop_bgr)
        if not fragments:
            return None, ParsedElectricalMarkings()

        joined_text = " ".join(text for text, _ in fragments).strip()
        if not joined_text:
            return None, ParsedElectricalMarkings()

        # Conservative confidence: minimum or length-weighted mean biased toward weakest critical token
        avg_conf = sum(conf for _, conf in fragments) / len(fragments)
        min_conf = min(conf for _, conf in fragments)
        combined_conf = round(max(0.0, min(1.0, 0.7 * avg_conf + 0.3 * min_conf)), 4)

        reading = OCRReading(
            raw_text=joined_text[:256],
            normalized_text=joined_text.upper()[:256],
            confidence=combined_conf,
            requires_human_review=combined_conf < self._confidence_threshold,
        )
        parsed = parse_electrical_faceplate_text(joined_text)
        return reading, parsed
