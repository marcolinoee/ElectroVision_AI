"""Image preprocessing: color constancy (white balance) and perspective/rotation deskew.

Applied strictly BEFORE OCR and cable color analysis to neutralize warm/fluorescent
electrical room lighting and camera tilt.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class PreprocessResult:
    """Output of panel image preprocessing."""

    image_bgr: np.ndarray
    white_balance_gains: tuple[float, float, float]
    deskew_angle_deg: float
    perspective_corrected: bool


def apply_color_constancy_gray_world(image_bgr: np.ndarray) -> tuple[np.ndarray, tuple[float, float, float]]:
    """Apply Shades-of-Gray / Gray-World white balance + gentle LAB luminance normalization.

    Neutralizes color casts (yellow incandescent / greenish fluorescent) so light-blue
    (Neutral) and green (PE) cable insulation colors remain accurately separable.
    """
    img_float = image_bgr.astype(np.float32)
    # Exclude clipped highlights and deep shadows from illuminant estimation
    luminance = 0.114 * img_float[:, :, 0] + 0.587 * img_float[:, :, 1] + 0.299 * img_float[:, :, 2]
    mask = (luminance > 20.0) & (luminance < 235.0)
    if np.count_nonzero(mask) < 100:
        mask = np.ones(luminance.shape, dtype=bool)

    mean_b = float(np.mean(img_float[:, :, 0][mask])) + 1e-5
    mean_g = float(np.mean(img_float[:, :, 1][mask])) + 1e-5
    mean_r = float(np.mean(img_float[:, :, 2][mask])) + 1e-5

    gray_mean = (mean_b + mean_g + mean_r) / 3.0
    # Clamp gains to avoid extreme amplification on monochromatic images
    gain_b = float(np.clip(gray_mean / mean_b, 0.65, 1.55))
    gain_g = float(np.clip(gray_mean / mean_g, 0.65, 1.55))
    gain_r = float(np.clip(gray_mean / mean_r, 0.65, 1.55))

    balanced = np.empty_like(img_float)
    balanced[:, :, 0] = np.clip(img_float[:, :, 0] * gain_b, 0.0, 255.0)
    balanced[:, :, 1] = np.clip(img_float[:, :, 1] * gain_g, 0.0, 255.0)
    balanced[:, :, 2] = np.clip(img_float[:, :, 2] * gain_r, 0.0, 255.0)

    balanced_u8 = balanced.astype(np.uint8)

    # Mild CLAHE on L channel only (preserves chromaticity a/b for cable color fidelity)
    lab = cv2.cvtColor(balanced_u8, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8))
    l_norm = clahe.apply(l_channel)
    merged = cv2.merge((l_norm, a_channel, b_channel))
    result_bgr = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)

    return result_bgr, (round(gain_b, 4), round(gain_g, 4), round(gain_r, 4))


def estimate_skew_angle_deg(image_bgr: np.ndarray, max_abs_angle: float = 20.0) -> float:
    """Estimate dominant DIN-rail / breaker horizontal skew angle in degrees via Hough lines."""
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150, apertureSize=3)

    h, w = gray.shape[:2]
    min_len = max(30, int(min(h, w) * 0.15))
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180.0,
        threshold=60,
        minLineLength=min_len,
        maxLineGap=15,
    )
    if lines is None or len(lines) == 0:
        return 0.0

    angles: list[float] = []
    for line in lines[:, 0]:
        x1, y1, x2, y2 = int(line[0]), int(line[1]), int(line[2]), int(line[3])
        dx = x2 - x1
        dy = y2 - y1
        if dx == 0:
            continue
        angle = float(np.degrees(np.arctan2(dy, dx)))
        if abs(angle) <= max_abs_angle:
            angles.append(angle)

    if not angles:
        return 0.0
    return float(np.median(angles))


def deskew_panel_image(image_bgr: np.ndarray, min_angle_threshold: float = 0.75) -> tuple[np.ndarray, float, bool]:
    """Correct rotational skew of an electrical panel image around its center."""
    angle = estimate_skew_angle_deg(image_bgr)
    if abs(angle) < min_angle_threshold:
        return image_bgr, 0.0, False

    h, w = image_bgr.shape[:2]
    center = (w / 2.0, h / 2.0)
    rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)
    deskewed = cv2.warpAffine(
        image_bgr,
        rot_mat,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return deskewed, round(angle, 3), True


def preprocess_panel_image(image_bgr: np.ndarray) -> PreprocessResult:
    """Full deterministic preprocessing pipeline: color constancy -> perspective/rotation deskew."""
    if image_bgr is None or image_bgr.size == 0:
        raise ValueError("Empty image provided to preprocess_panel_image.")

    balanced, gains = apply_color_constancy_gray_world(image_bgr)
    deskewed, angle_deg, corrected = deskew_panel_image(balanced)
    return PreprocessResult(
        image_bgr=deskewed,
        white_balance_gains=gains,
        deskew_angle_deg=angle_deg,
        perspective_corrected=corrected,
    )
