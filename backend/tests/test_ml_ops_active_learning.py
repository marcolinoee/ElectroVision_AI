"""Tests for Phase 2 MLOps: Active Learning dataset builder, Golden Holdout gatekeeper, Atomic Registry."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import yaml

from app.models.enums import ComponentType, DatasetSplit
from app.schemas.digital_twin import BoundingBox, DigitalTwinJSON, PanelComponent, PanelMetadata
from app.services.ml_ops.atomic_registry import AtomicModelRegistry
from app.services.ml_ops.dataset_builder import (
    SampleRecord,
    build_active_learning_dataset,
    export_human_correction_sample,
)
from app.services.ml_ops.golden_set_eval import (
    GoldenEvaluationMetrics,
    evaluate_promotion_gate,
)
from app.services.ml_ops.yolo_trainer import run_active_learning_cycle


class _StubTrainerBackend:
    def __init__(self, metrics: GoldenEvaluationMetrics, payload: bytes = b"candidate-weights") -> None:
        self._metrics = metrics
        self._payload = payload

    def train(
        self,
        base_weights: Path,
        data_yaml: Path,
        output_run_dir: Path,
        epochs: int,
        device: str,
    ) -> Path:
        best_pt = output_run_dir / "weights" / "best.pt"
        best_pt.parent.mkdir(parents=True, exist_ok=True)
        best_pt.write_bytes(self._payload)
        return best_pt

    def evaluate_golden(
        self,
        weights_path: Path,
        data_yaml: Path,
        device: str,
    ) -> GoldenEvaluationMetrics:
        return self._metrics


def _write_fake_sample(root: Path, name: str, content: bytes) -> SampleRecord:
    img = root / f"{name}.jpg"
    lbl = root / f"{name}.txt"
    img.write_bytes(content)
    lbl.write_text("2 0.500000 0.500000 0.200000 0.300000\n", encoding="utf-8")
    return SampleRecord(image_path=img, label_path=lbl, split=DatasetSplit.TRAIN, source="replay")


def test_dataset_builder_mixes_replay_buffer_and_isolates_golden_holdout(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()

    # Export a real human-corrected DigitalTwinJSON
    src_img = staging / "human_src.jpg"
    src_img.write_bytes(b"\xff\xd8\xffhuman-panel-image-bytes")
    twin = DigitalTwinJSON(
        project_id=uuid4(),
        inspection_id=uuid4(),
        panel=PanelMetadata(panel_id="Q1", name="Quadro 1"),
        components=[
            PanelComponent(
                component_id="IDR-1",
                label="IDR1",
                component_type=ComponentType.IDR,
                bbox=BoundingBox(x=0.2, y=0.2, w=0.2, h=0.4),
                verified_by_human=True,
            )
        ],
    )
    img_p, lbl_p, _sha, counts = export_human_correction_sample(
        digital_twin=twin,
        source_image_path=src_img,
        staging_dir=staging / "human",
        base_dir=tmp_path,
    )
    assert counts == {"IDR": 1}
    assert lbl_p.read_text(encoding="utf-8").strip().startswith("2 0.300000 0.400000 0.200000 0.400000")

    human_rec = SampleRecord(img_p, lbl_p, DatasetSplit.TRAIN, "human_correction", False)
    human_rec_2 = _write_fake_sample(staging, "human2", b"unique-human-2")
    replay_recs = [_write_fake_sample(staging, f"replay_{i}", f"replay-{i}".encode()) for i in range(4)]
    golden_rec = _write_fake_sample(staging, "golden_0", b"locked-golden-image-bytes")
    golden_locked = SampleRecord(
        golden_rec.image_path, golden_rec.label_path, DatasetSplit.GOLDEN_HOLDOUT, "golden_seed", True
    )
    # Deliberately attempt to leak a duplicate of the golden image into human_corrections
    leaked_golden_dup = _write_fake_sample(staging, "leaked_dup", b"locked-golden-image-bytes")

    bundle = build_active_learning_dataset(
        human_corrections=[human_rec, human_rec_2, leaked_golden_dup],
        replay_buffer=replay_recs,
        golden_holdout=[golden_locked],
        output_dataset_dir=tmp_path / "dataset_out",
        replay_ratio=1.0,
        base_dir=tmp_path,
    )
    # Leaked golden duplicate MUST have been filtered out (only 2 clean human corrections remain)
    assert bundle.human_correction_count == 2
    assert bundle.replay_count == 2
    assert bundle.golden_count == 1
    assert bundle.train_count + bundle.val_count == 4

    parsed_yaml = yaml.safe_load(bundle.data_yaml_path.read_text(encoding="utf-8"))
    assert parsed_yaml["test"] == "images/golden_holdout"
    assert parsed_yaml["names"][2] == "IDR"


def test_golden_holdout_gatekeeper_enforces_map_and_critical_recall() -> None:
    # 1. Fails if mAP50-95 does not improve
    m_no_gain = GoldenEvaluationMetrics(
        map50=0.90, map50_95=0.72, recall_idr=0.98, recall_dps=0.97, recall_disjuntor=0.99
    )
    d1 = evaluate_promotion_gate(m_no_gain, baseline_map50_95=0.75)
    assert d1.approved is False
    assert any("mAP50-95" in r for r in d1.reasons)

    # 2. Fails if mAP50-95 improves BUT IDR recall < 0.95
    m_low_idr = GoldenEvaluationMetrics(
        map50=0.92, map50_95=0.80, recall_idr=0.92, recall_dps=0.98, recall_disjuntor=0.99
    )
    d2 = evaluate_promotion_gate(m_low_idr, baseline_map50_95=0.75)
    assert d2.approved is False
    assert any("IDR" in r for r in d2.reasons)

    # 3. Fails if DPS recall < 0.95
    m_low_dps = GoldenEvaluationMetrics(
        map50=0.92, map50_95=0.80, recall_idr=0.97, recall_dps=0.94, recall_disjuntor=0.99
    )
    d3 = evaluate_promotion_gate(m_low_dps, baseline_map50_95=0.75)
    assert d3.approved is False
    assert any("DPS" in r for r in d3.reasons)

    # 4. Approves when mAP50-95 improves AND all critical recalls >= 0.95
    m_good = GoldenEvaluationMetrics(
        map50=0.94, map50_95=0.81, recall_idr=0.96, recall_dps=0.95, recall_disjuntor=0.98
    )
    d4 = evaluate_promotion_gate(m_good, baseline_map50_95=0.75)
    assert d4.approved is True


def test_active_learning_cycle_and_atomic_registry_promotion_and_rollback(tmp_path: Path) -> None:
    models_dir = tmp_path / "models_weights"
    registry = AtomicModelRegistry(models_dir=models_dir, base_dir=tmp_path)

    # Seed initial v1 active model
    v1_src = tmp_path / "v1_init.pt"
    v1_src.write_bytes(b"v1-baseline-weights")
    registry.register_candidate(v1_src, version_tag="v1_0", promote=True)
    assert registry.active_weights_path.read_bytes() == b"v1-baseline-weights"

    dummy_yaml = tmp_path / "data.yaml"
    dummy_yaml.write_text("path: .\n", encoding="utf-8")

    # Candidate v2 fails IDR recall (< 0.95) -> archived, NOT promoted!
    rejected = run_active_learning_cycle(
        base_weights=registry.active_weights_path,
        data_yaml=dummy_yaml,
        baseline_map50_95=0.70,
        version_tag="v2_0_bad_idr",
        models_dir=models_dir,
        run_output_dir=tmp_path / "run_v2",
        backend=_StubTrainerBackend(
            GoldenEvaluationMetrics(0.92, 0.78, 0.91, 0.97, 0.98),
            payload=b"v2-unsafe-weights",
        ),
        base_dir=tmp_path,
    )
    assert rejected.decision.approved is False
    assert rejected.registered.promoted is False
    assert registry.active_weights_path.read_bytes() == b"v1-baseline-weights"

    # Candidate v3 improves mAP50-95 AND passes all recalls >= 0.95 -> atomically promoted!
    approved = run_active_learning_cycle(
        base_weights=registry.active_weights_path,
        data_yaml=dummy_yaml,
        baseline_map50_95=0.70,
        version_tag="v3_0_safe",
        models_dir=models_dir,
        run_output_dir=tmp_path / "run_v3",
        backend=_StubTrainerBackend(
            GoldenEvaluationMetrics(0.95, 0.82, 0.97, 0.96, 0.99),
            payload=b"v3-promoted-weights",
        ),
        base_dir=tmp_path,
    )
    assert approved.decision.approved is True
    assert approved.registered.promoted is True
    assert registry.active_weights_path.read_bytes() == b"v3-promoted-weights"
    manifest = registry.read_active_manifest()
    assert manifest is not None
    assert manifest["version_tag"] == "v3_0_safe"
    assert list(models_dir.glob("*.tmp")) == []

    # Rollback to v1_0 restores previous weights atomically
    registry.rollback_to_version("v1_0")
    assert registry.active_weights_path.read_bytes() == b"v1-baseline-weights"
