"""Unit & integration tests for Phase 2 Computer Vision pipeline (OpenCV + Pillow + OCR + Color)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from app.core.config import Settings
from app.models.enums import CableColor, ComponentType, TripCurve
from app.schemas.digital_twin import BoundingBox
from app.services.vision.color_analyzer import classify_cable_color
from app.services.vision.keyframe_extractor import extract_sharp_keyframes
from app.services.vision.ocr_reader import ElectricalOCRReader, parse_electrical_faceplate_text
from app.services.vision.pipeline import run_vision_inference_pipeline
from app.services.vision.preprocessor import (
    apply_color_constancy_gray_world,
    deskew_panel_image,
    preprocess_panel_image,
)
from app.services.vision.proxy_gen import generate_image_proxies
from app.services.vision.yolo_detector import RawDetection


class _StubOCRBackend:
    def __init__(self, responses: list[tuple[str, float]]) -> None:
        self._responses = responses

    def read_text(self, image_bgr: np.ndarray) -> list[tuple[str, float]]:
        return self._responses


class _StubDetector:
    def __init__(self, detections: list[RawDetection]) -> None:
        self._detections = detections

    def detect(self, image_bgr: np.ndarray) -> list[RawDetection]:
        return self._detections


def test_proxy_generator_creates_atomic_proxy_and_thumbnail(tmp_path: Path) -> None:
    src = tmp_path / "panel_4k.jpg"
    img = np.full((1800, 2400, 3), 180, dtype=np.uint8)
    cv2.imwrite(str(src), img)

    res = generate_image_proxies(
        source_image_path=src,
        output_dir=tmp_path / "proxies",
        stem="insp1",
        base_dir=tmp_path,
    )
    assert res.proxy_path.exists()
    assert res.thumbnail_path.exists()
    assert max(res.proxy_width, res.proxy_height) <= 1600
    assert max(res.thumb_width, res.thumb_height) <= 400
    assert list((tmp_path / "proxies").glob("*.tmp")) == []


def test_keyframe_extractor_selects_sharpest_frame_from_video(tmp_path: Path) -> None:
    video_path = tmp_path / "scan.avi"
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(str(video_path), fourcc, 10.0, (320, 240))
    assert writer.isOpened()

    # Write 4 blurry frames and 2 sharp checkerboard/text frames
    blurry = np.full((240, 320, 3), 120, dtype=np.uint8)
    sharp = np.zeros((240, 320, 3), dtype=np.uint8)
    for y in range(0, 240, 20):
        for x in range(0, 320, 20):
            if ((x // 20) + (y // 20)) % 2 == 0:
                sharp[y : y + 20, x : x + 20] = 255

    for idx in range(12):
        writer.write(sharp if idx in {4, 9} else blurry)
    writer.release()

    keyframes = extract_sharp_keyframes(
        video_path=video_path,
        output_dir=tmp_path / "frames",
        max_keyframes=3,
        sample_stride_frames=1,
        min_sharpness=50.0,
        base_dir=tmp_path,
    )
    assert len(keyframes) >= 1
    assert keyframes[0].sharpness_score > 100.0
    assert keyframes[0].file_path.exists()


def test_color_constancy_neutralizes_warm_tint_and_deskew_corrects_tilt() -> None:
    # Create warm-tinted gray card image (R >> B)
    warm = np.zeros((240, 320, 3), dtype=np.uint8)
    warm[:, :] = (90, 140, 210)  # BGR with heavy warm cast
    balanced, gains = apply_color_constancy_gray_world(warm)
    # Blue gain should be > Red gain to neutralize warm tint
    assert gains[0] > gains[2]
    assert balanced.shape == warm.shape

    # Create a panel image with tilted DIN rail lines (~8 degrees)
    canvas = np.full((300, 400, 3), 240, dtype=np.uint8)
    cv2.rectangle(canvas, (40, 90), (360, 130), (30, 30, 30), -1)
    cv2.rectangle(canvas, (40, 180), (360, 220), (30, 30, 30), -1)
    rot_mat = cv2.getRotationMatrix2D((200, 150), -8.0, 1.0)
    tilted = cv2.warpAffine(canvas, rot_mat, (400, 300), borderValue=(240, 240, 240))

    deskewed, angle, corrected = deskew_panel_image(tilted)
    assert corrected is True
    assert 5.0 <= abs(angle) <= 11.0
    assert deskewed.shape == tilted.shape

    full_res = preprocess_panel_image(tilted)
    assert full_res.image_bgr.shape == tilted.shape


def test_cable_color_analyzer_identifies_nbr5410_colors_and_flags_low_confidence() -> None:
    # Light-blue Neutral cable (BGR: 230, 160, 40 -> Hue ~ 103 in OpenCV)
    blue_crop = np.full((80, 80, 3), (230, 160, 40), dtype=np.uint8)
    res_blue = classify_cable_color(blue_crop)
    assert res_blue.color == CableColor.AZUL_CLARO
    assert res_blue.confidence >= 0.80
    assert res_blue.requires_human_review is False

    # Green PE cable (BGR: 40, 180, 40 -> Hue ~ 60)
    green_crop = np.full((80, 80, 3), (40, 180, 40), dtype=np.uint8)
    res_green = classify_cable_color(green_crop)
    assert res_green.color == CableColor.VERDE
    assert res_green.requires_human_review is False

    # Green-Yellow striped PE cable
    striped = np.zeros((80, 80, 3), dtype=np.uint8)
    striped[:, :40] = (40, 180, 40)  # Green
    striped[:, 40:] = (20, 220, 230)  # Yellow (BGR)
    res_striped = classify_cable_color(striped)
    assert res_striped.color == CableColor.VERDE_AMARELO
    assert res_striped.requires_human_review is False

    # Noisy mixed crop -> low confidence -> requires_human_review=True
    rng = np.random.default_rng(42)
    noisy = rng.integers(0, 255, size=(80, 80, 3), dtype=np.uint8)
    res_noisy = classify_cable_color(noisy)
    assert res_noisy.requires_human_review is True


def test_ocr_parser_and_confidence_review_threshold() -> None:
    parsed_breaker = parse_electrical_faceplate_text("WEG MDW C20 6kA 230/400V")
    assert parsed_breaker.trip_curve == TripCurve.C
    assert parsed_breaker.rated_current_a == 20.0
    assert parsed_breaker.breaking_capacity_ka == 6.0

    parsed_idr = parse_electrical_faceplate_text("IDR 40A 30mA")
    assert parsed_idr.rated_current_a == 40.0
    assert parsed_idr.sensitivity_ma == 30

    parsed_dps = parse_electrical_faceplate_text("DPS Classe II 275V 45kA")
    assert parsed_dps.dps_class == "II"
    assert parsed_dps.voltage_v == 275.0
    assert parsed_dps.breaking_capacity_ka == 45.0

    crop = np.full((40, 80, 3), 200, dtype=np.uint8)
    low_conf_reader = ElectricalOCRReader(backend=_StubOCRBackend([("C16", 0.65)]))
    reading, parsed = low_conf_reader.read_component_crop(crop)
    assert reading is not None
    assert reading.requires_human_review is True
    assert parsed.rated_current_a == 16.0


def test_end_to_end_vision_pipeline_builds_digital_twin(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    settings = Settings(storage_root=storage_root)
    settings.ensure_storage_directories()

    # Synthetic panel image: top-left breaker, bottom-right light-blue neutral cable
    img = np.full((400, 400, 3), 220, dtype=np.uint8)
    img[240:360, 240:360] = (230, 160, 40)  # Light-blue cable region
    img_path = settings.uploads_dir / "panel.jpg"
    cv2.imwrite(str(img_path), img)

    detector = _StubDetector(
        detections=[
            RawDetection(
                class_id=0,
                component_type=ComponentType.DISJUNTOR_GERAL,
                bbox=BoundingBox(x=0.1, y=0.1, w=0.3, h=0.3),
                confidence=0.94,
                requires_human_review=False,
            ),
            RawDetection(
                class_id=2,
                component_type=ComponentType.IDR,
                bbox=BoundingBox(x=0.45, y=0.1, w=0.25, h=0.3),
                confidence=0.71,  # < 0.80 -> must require human review
                requires_human_review=True,
            ),
            RawDetection(
                class_id=8,
                component_type=ComponentType.CABO_NEUTRO,
                bbox=BoundingBox(x=0.6, y=0.6, w=0.3, h=0.3),
                confidence=0.92,
                requires_human_review=False,
            ),
        ]
    )
    ocr_reader = ElectricalOCRReader(backend=_StubOCRBackend([("C50 6kA 30mA", 0.91)]))

    out = run_vision_inference_pipeline(
        project_id=uuid4(),
        inspection_id=uuid4(),
        media_path=img_path,
        detector=detector,
        ocr_reader=ocr_reader,
        settings=settings,
        panel_name="QDC Teste",
    )
    assert out.total_components == 3
    assert out.pending_review_count == 1  # IDR with 0.71 confidence
    assert out.proxy_path.exists()
    assert out.digital_twin.panel.has_idr is True
    assert out.digital_twin.panel.main_breaker_id == "COMP-001"
    cable_comp = out.digital_twin.components[2]
    assert cable_comp.cable_spec is not None
    assert cable_comp.cable_spec.color == CableColor.AZUL_CLARO
