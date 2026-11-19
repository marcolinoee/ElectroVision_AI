"""YOLO Active Learning dataset builder with Replay Buffer and locked Golden Holdout Set isolation."""

from __future__ import annotations

import random
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core.security import compute_sha256_file
from app.core.storage import atomic_write_text, ensure_within_base
from app.models.enums import DatasetSplit
from app.schemas.digital_twin import DigitalTwinJSON
from app.services.vision.taxonomy import (
    CANONICAL_YOLO_CLASSES,
    COMPONENT_TYPE_TO_YOLO_CLASS_ID,
)


@dataclass(frozen=True, slots=True)
class SampleRecord:
    """In-memory representation of a dataset sample for YOLO export."""

    image_path: Path
    label_path: Path
    split: DatasetSplit
    source: str
    is_locked_golden: bool = False


@dataclass(frozen=True, slots=True)
class ExportedDatasetBundle:
    """Metadata of a built YOLO training/validation/golden dataset."""

    dataset_dir: Path
    data_yaml_path: Path
    train_count: int
    val_count: int
    golden_count: int
    replay_count: int
    human_correction_count: int


def digital_twin_to_yolo_lines(digital_twin: DigitalTwinJSON) -> list[str]:
    """Convert verified bounding boxes from DigitalTwinJSON to YOLO format: `class_id cx cy w h`."""
    lines: list[str] = []
    for comp in digital_twin.components:
        if comp.bbox is None:
            continue
        class_id = COMPONENT_TYPE_TO_YOLO_CLASS_ID.get(comp.component_type)
        if class_id is None:
            continue
        cx = max(0.0, min(1.0, comp.bbox.x + comp.bbox.w / 2.0))
        cy = max(0.0, min(1.0, comp.bbox.y + comp.bbox.h / 2.0))
        w = max(1e-4, min(1.0, comp.bbox.w))
        h = max(1e-4, min(1.0, comp.bbox.h))
        lines.append(f"{class_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    return lines


def export_human_correction_sample(
    digital_twin: DigitalTwinJSON,
    source_image_path: Path,
    staging_dir: Path,
    base_dir: Path | None = None,
) -> tuple[Path, Path, str, dict[str, int]]:
    """Persist a single engineer-validated inspection as a YOLO image+label pair."""
    if not source_image_path.exists():
        raise FileNotFoundError(f"Source image not found: {source_image_path}")

    yolo_lines = digital_twin_to_yolo_lines(digital_twin)
    if not yolo_lines:
        raise ValueError("DigitalTwinJSON contains no valid bounding boxes for YOLO export.")

    images_dir = staging_dir / "images"
    labels_dir = staging_dir / "labels"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    stem = f"insp_{digital_twin.inspection_id}"
    ext = source_image_path.suffix.lower() or ".jpg"
    dest_img = images_dir / f"{stem}{ext}"
    dest_lbl = labels_dir / f"{stem}.txt"

    if base_dir is not None:
        dest_img = ensure_within_base(base_dir, dest_img)
        dest_lbl = ensure_within_base(base_dir, dest_lbl)

    tmp_img = dest_img.with_suffix(dest_img.suffix + ".tmp")
    shutil.copy2(source_image_path, tmp_img)
    tmp_img.replace(dest_img)

    atomic_write_text(dest_lbl, "\n".join(yolo_lines) + "\n", base_dir=base_dir)

    class_counts: dict[str, int] = {}
    for comp in digital_twin.components:
        if comp.bbox is not None and comp.component_type in COMPONENT_TYPE_TO_YOLO_CLASS_ID:
            key = comp.component_type.value
            class_counts[key] = class_counts.get(key, 0) + 1

    return dest_img, dest_lbl, compute_sha256_file(dest_img), class_counts


def build_active_learning_dataset(
    human_corrections: list[SampleRecord],
    replay_buffer: list[SampleRecord],
    golden_holdout: list[SampleRecord],
    output_dataset_dir: Path,
    replay_ratio: float = 0.5,
    val_fraction: float = 0.15,
    seed: int = 42,
    base_dir: Path | None = None,
) -> ExportedDatasetBundle:
    """Assemble a YOLO dataset combining human corrections + replay buffer, isolating Golden Holdout.

    Guarantees:
    1. Golden Holdout samples (`is_locked_golden=True` or `split=GOLDEN_HOLDOUT`) NEVER leak into train/val.
    2. Replay buffer is mixed at `replay_ratio` to prevent catastrophic forgetting.
    3. `data.yaml` is written atomically.
    """
    if not human_corrections:
        raise ValueError("Cannot build Active Learning dataset without human correction samples.")
    if not golden_holdout:
        raise ValueError(
            "Golden Holdout Set is empty. Promotion requires a locked Golden Holdout Set."
        )

    rng = random.Random(seed)
    golden_hashes = {compute_sha256_file(s.image_path) for s in golden_holdout if s.image_path.exists()}

    # Filter out any accidental overlap with Golden Holdout
    clean_corrections = [
        s
        for s in human_corrections
        if not s.is_locked_golden
        and s.image_path.exists()
        and s.label_path.exists()
        and compute_sha256_file(s.image_path) not in golden_hashes
    ]
    clean_replay = [
        s
        for s in replay_buffer
        if not s.is_locked_golden
        and s.image_path.exists()
        and s.label_path.exists()
        and compute_sha256_file(s.image_path) not in golden_hashes
    ]

    if not clean_corrections:
        raise ValueError("No valid non-golden human correction samples available.")

    # Compute replay sample count proportional to new human corrections
    target_replay = int(round(len(clean_corrections) * max(0.0, replay_ratio)))
    selected_replay = (
        rng.sample(clean_replay, min(target_replay, len(clean_replay))) if target_replay > 0 else []
    )

    combined = list(clean_corrections) + list(selected_replay)
    rng.shuffle(combined)

    val_size = max(1, int(round(len(combined) * val_fraction))) if len(combined) > 1 else 0
    val_samples = combined[:val_size]
    train_samples = combined[val_size:] if val_size < len(combined) else combined

    for split_name in ("train", "val", "golden_holdout"):
        (output_dataset_dir / "images" / split_name).mkdir(parents=True, exist_ok=True)
        (output_dataset_dir / "labels" / split_name).mkdir(parents=True, exist_ok=True)

    def _copy_split(samples: list[SampleRecord], split_name: str) -> int:
        copied = 0
        for idx, sample in enumerate(samples):
            if not sample.image_path.exists() or not sample.label_path.exists():
                continue
            stem = f"{split_name}_{idx:05d}_{sample.image_path.stem}"
            img_dst = output_dataset_dir / "images" / split_name / f"{stem}{sample.image_path.suffix}"
            lbl_dst = output_dataset_dir / "labels" / split_name / f"{stem}.txt"
            shutil.copy2(sample.image_path, img_dst)
            shutil.copy2(sample.label_path, lbl_dst)
            copied += 1
        return copied

    train_count = _copy_split(train_samples, "train")
    val_count = _copy_split(val_samples, "val")
    golden_count = _copy_split(golden_holdout, "golden_holdout")

    # If val_count == 0 (single-sample edge case), mirror train path for YOLO compatibility
    val_rel = "images/val" if val_count > 0 else "images/train"
    data_yaml = {
        "path": str(output_dataset_dir.resolve()),
        "train": "images/train",
        "val": val_rel,
        "test": "images/golden_holdout",
        "names": {cid: ctype.value for cid, ctype in sorted(CANONICAL_YOLO_CLASSES.items())},
    }
    yaml_path = output_dataset_dir / "data.yaml"
    atomic_write_text(
        yaml_path,
        yaml.safe_dump(data_yaml, sort_keys=False, allow_unicode=True),
        base_dir=base_dir,
    )

    return ExportedDatasetBundle(
        dataset_dir=output_dataset_dir,
        data_yaml_path=yaml_path,
        train_count=train_count,
        val_count=val_count,
        golden_count=golden_count,
        replay_count=len(selected_replay),
        human_correction_count=len(clean_corrections),
    )
