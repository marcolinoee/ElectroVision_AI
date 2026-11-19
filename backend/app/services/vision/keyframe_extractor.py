"""Sharpness-aware video keyframe extractor using OpenCV Laplacian variance scoring."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.core.storage import atomic_write_bytes


@dataclass(frozen=True, slots=True)
class ExtractedKeyframe:
    """Metadata for an extracted sharp video keyframe."""

    frame_index: int
    timestamp_sec: float
    sharpness_score: float
    file_path: Path


def compute_sharpness_score(frame_bgr: np.ndarray) -> float:
    """Compute focus/sharpness metric via variance of the Laplacian on grayscale image."""
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def extract_sharp_keyframes(
    video_path: Path,
    output_dir: Path,
    max_keyframes: int = 5,
    sample_stride_frames: int = 10,
    min_sharpness: float = 20.0,
    base_dir: Path | None = None,
) -> list[ExtractedKeyframe]:
    """Extract the sharpest, temporally distributed keyframes from a local video file.

    Uses window-based temporal stratification so keyframes cover the full panel scan
    rather than clustering on a single second.
    """
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"Unable to open video stream: {video_path}")

    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
        if fps <= 0.0:
            fps = 30.0

        candidates: list[tuple[int, float, float, np.ndarray]] = []
        frame_idx = 0
        stride = max(1, sample_stride_frames)

        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            if frame_idx % stride == 0:
                score = compute_sharpness_score(frame)
                if score >= min_sharpness:
                    candidates.append((frame_idx, frame_idx / fps, score, frame.copy()))
            frame_idx += 1

        if not candidates:
            # Fallback: grab first readable frame even if below sharpness threshold
            capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = capture.read()
            if ok and frame is not None:
                score = compute_sharpness_score(frame)
                candidates.append((0, 0.0, score, frame.copy()))

        if not candidates:
            raise ValueError(f"No readable frames found in video: {video_path}")

        # Partition candidates into temporal buckets and pick the sharpest frame per bucket
        num_buckets = min(max_keyframes, len(candidates))
        bucket_size = max(1, len(candidates) // num_buckets)
        selected: list[tuple[int, float, float, np.ndarray]] = []
        for b in range(num_buckets):
            start = b * bucket_size
            end = len(candidates) if b == num_buckets - 1 else (b + 1) * bucket_size
            bucket = candidates[start:end]
            best = max(bucket, key=lambda item: item[2])
            selected.append(best)

        # Sort final keyframes by sharpness descending so index 0 is the primary sharp frame
        selected.sort(key=lambda item: item[2], reverse=True)

        output_dir.mkdir(parents=True, exist_ok=True)
        results: list[ExtractedKeyframe] = []
        for rank, (idx, ts_sec, score, frame_bgr) in enumerate(selected, start=1):
            ok_enc, encoded = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if not ok_enc:
                continue
            dest = output_dir / f"keyframe_{rank:02d}_f{idx:06d}.jpg"
            atomic_write_bytes(dest, encoded.tobytes(), base_dir=base_dir)
            results.append(
                ExtractedKeyframe(
                    frame_index=idx,
                    timestamp_sec=round(ts_sec, 3),
                    sharpness_score=round(score, 2),
                    file_path=dest,
                )
            )
        return results
    finally:
        capture.release()
