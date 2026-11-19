"""Deterministic cable insulation color classifier (NBR 5410: azul-claro Neutral, verde/verde-amarelo PE)."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.models.enums import CableColor
from app.schemas.digital_twin import CONFIDENCE_REVIEW_THRESHOLD


@dataclass(frozen=True, slots=True)
class CableColorResult:
    """Classified cable color with confidence and automatic < 0.80 human review flag."""

    color: CableColor
    confidence: float
    requires_human_review: bool
    dominant_hsv: tuple[float, float, float]


def classify_cable_color(
    crop_bgr: np.ndarray,
    confidence_threshold: float = CONFIDENCE_REVIEW_THRESHOLD,
) -> CableColorResult:
    """Classify conductor insulation color from a color-constancy-corrected BGR crop.

    Focuses on the central 60% ROI to minimize background DIN-rail / busbar bleed.
    Uses OpenCV HSV scale: H in [0, 179], S in [0, 255], V in [0, 255].
    """
    if crop_bgr is None or crop_bgr.size == 0:
        return CableColorResult(
            color=CableColor.DESCONHECIDA,
            confidence=0.0,
            requires_human_review=True,
            dominant_hsv=(0.0, 0.0, 0.0),
        )

    h, w = crop_bgr.shape[:2]
    y0, y1 = int(h * 0.2), max(int(h * 0.8), int(h * 0.2) + 1)
    x0, x1 = int(w * 0.2), max(int(w * 0.8), int(w * 0.2) + 1)
    roi = crop_bgr[y0:y1, x0:x1]

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    h_ch = hsv[:, :, 0].astype(np.float32)
    s_ch = hsv[:, :, 1].astype(np.float32)
    v_ch = hsv[:, :, 2].astype(np.float32)
    total_px = float(hsv.shape[0] * hsv.shape[1])

    # Chromatic masks tuned for NBR 5410 insulation colors
    blue_mask = (h_ch >= 88) & (h_ch <= 130) & (s_ch >= 55) & (v_ch >= 60)
    green_mask = (h_ch >= 38) & (h_ch <= 85) & (s_ch >= 55) & (v_ch >= 45)
    yellow_mask = (h_ch >= 18) & (h_ch <= 37) & (s_ch >= 70) & (v_ch >= 70)
    red_mask = ((h_ch <= 10) | (h_ch >= 165)) & (s_ch >= 75) & (v_ch >= 50)
    brown_mask = (h_ch >= 8) & (h_ch <= 22) & (s_ch >= 50) & (v_ch >= 25) & (v_ch <= 150)

    # Achromatic masks
    black_mask = v_ch < 55
    white_mask = (s_ch < 38) & (v_ch >= 195)
    gray_mask = (s_ch < 42) & (v_ch >= 55) & (v_ch < 195)

    ratios: dict[CableColor, float] = {
        CableColor.AZUL_CLARO: float(np.count_nonzero(blue_mask)) / total_px,
        CableColor.VERDE: float(np.count_nonzero(green_mask)) / total_px,
        CableColor.AMARELO: float(np.count_nonzero(yellow_mask)) / total_px,
        CableColor.VERMELHO: float(np.count_nonzero(red_mask)) / total_px,
        CableColor.MARROM: float(np.count_nonzero(brown_mask)) / total_px,
        CableColor.PRETO: float(np.count_nonzero(black_mask)) / total_px,
        CableColor.BRANCO: float(np.count_nonzero(white_mask)) / total_px,
        CableColor.CINZA: float(np.count_nonzero(gray_mask)) / total_px,
    }

    # Special case: Green + Yellow striped PE conductor (VERDE_AMARELO)
    green_ratio = ratios[CableColor.VERDE]
    yellow_ratio = ratios[CableColor.AMARELO]
    if green_ratio >= 0.20 and yellow_ratio >= 0.15 and (green_ratio + yellow_ratio) >= 0.45:
        combined_conf = min(0.99, round(green_ratio + yellow_ratio, 4))
        return CableColorResult(
            color=CableColor.VERDE_AMARELO,
            confidence=combined_conf,
            requires_human_review=combined_conf < confidence_threshold,
            dominant_hsv=(
                round(float(np.median(h_ch)), 1),
                round(float(np.median(s_ch)), 1),
                round(float(np.median(v_ch)), 1),
            ),
        )

    best_color, best_ratio = max(ratios.items(), key=lambda kv: kv[1])
    if best_ratio < 0.25:
        best_color = CableColor.DESCONHECIDA
        confidence = round(best_ratio, 4)
    else:
        confidence = min(0.99, round(best_ratio, 4))

    return CableColorResult(
        color=best_color,
        confidence=confidence,
        requires_human_review=confidence < confidence_threshold,
        dominant_hsv=(
            round(float(np.median(h_ch)), 1),
            round(float(np.median(s_ch)), 1),
            round(float(np.median(v_ch)), 1),
        ),
    )
