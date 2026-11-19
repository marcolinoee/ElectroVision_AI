"""Golden Holdout Set evaluation & strict safety promotion gatekeeper.

Guardrail:
A candidate .pt model is promoted ONLY IF:
  1. candidate.map50_95 > baseline.map50_95 (strict improvement on fixed Golden Holdout Set)
  2. Recall >= 0.95 on ALL critical protection classes: IDR, DPS, and Disjuntor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.models.enums import ComponentType
from app.services.vision.taxonomy import COMPONENT_TYPE_TO_YOLO_CLASS_ID

logger = get_logger(__name__)

MIN_CRITICAL_PROTECTION_RECALL: float = 0.95


@dataclass(frozen=True, slots=True)
class GoldenEvaluationMetrics:
    """Evaluation metrics computed on the locked Golden Holdout Set."""

    map50: float
    map50_95: float
    recall_idr: float
    recall_dps: float
    recall_disjuntor: float
    per_class_recall: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    """Deterministic decision on whether a candidate model may replace active.pt."""

    approved: bool
    reasons: list[str]
    candidate_metrics: GoldenEvaluationMetrics
    baseline_map50_95: float


def evaluate_promotion_gate(
    candidate: GoldenEvaluationMetrics,
    baseline_map50_95: float,
    min_critical_recall: float = MIN_CRITICAL_PROTECTION_RECALL,
) -> PromotionDecision:
    """Enforce mandatory Golden Holdout Set improvement and >= 0.95 critical protection recall."""
    reasons: list[str] = []

    if candidate.map50_95 <= baseline_map50_95:
        reasons.append(
            f"mAP50-95 did not improve over baseline "
            f"(candidate={candidate.map50_95:.4f} <= baseline={baseline_map50_95:.4f})."
        )

    if candidate.recall_idr < min_critical_recall:
        reasons.append(
            f"Critical protection class IDR recall below safety floor "
            f"({candidate.recall_idr:.4f} < {min_critical_recall:.2f})."
        )

    if candidate.recall_dps < min_critical_recall:
        reasons.append(
            f"Critical protection class DPS recall below safety floor "
            f"({candidate.recall_dps:.4f} < {min_critical_recall:.2f})."
        )

    if candidate.recall_disjuntor < min_critical_recall:
        reasons.append(
            f"Critical protection class Disjuntor recall below safety floor "
            f"({candidate.recall_disjuntor:.4f} < {min_critical_recall:.2f})."
        )

    approved = len(reasons) == 0
    if approved:
        reasons.append(
            f"Approved: mAP50-95 improved ({baseline_map50_95:.4f} -> {candidate.map50_95:.4f}) "
            f"and all critical recalls >= {min_critical_recall:.2f}."
        )

    return PromotionDecision(
        approved=approved,
        reasons=reasons,
        candidate_metrics=candidate,
        baseline_map50_95=baseline_map50_95,
    )


def run_yolo_golden_evaluation(
    weights_path: Path,
    data_yaml_path: Path,
    device: str = "cpu",
) -> GoldenEvaluationMetrics:
    """Run Ultralytics YOLO validation on the `test` split (locked Golden Holdout Set)."""
    from ultralytics import YOLO  # Lazy import isolated to worker-ml

    if not weights_path.exists():
        raise FileNotFoundError(f"Candidate weights not found: {weights_path}")
    if not data_yaml_path.exists():
        raise FileNotFoundError(f"Dataset YAML not found: {data_yaml_path}")

    logger.info("evaluating_golden_holdout", weights=str(weights_path), device=device)
    model = YOLO(str(weights_path))
    val_res: Any = model.val(
        data=str(data_yaml_path),
        split="test",
        device=device,
        verbose=False,
    )

    box_metrics = val_res.box
    map50 = float(getattr(box_metrics, "map50", 0.0))
    map50_95 = float(getattr(box_metrics, "map", 0.0))
    recalls_arr = list(getattr(box_metrics, "r", []))
    class_indices = list(getattr(box_metrics, "ap_class_index", []))

    idx_to_recall: dict[int, float] = {
        int(cls_idx): float(recalls_arr[pos])
        for pos, cls_idx in enumerate(class_indices)
        if pos < len(recalls_arr)
    }

    idr_id = COMPONENT_TYPE_TO_YOLO_CLASS_ID[ComponentType.IDR]
    dps_id = COMPONENT_TYPE_TO_YOLO_CLASS_ID[ComponentType.DPS]
    dj_geral_id = COMPONENT_TYPE_TO_YOLO_CLASS_ID[ComponentType.DISJUNTOR_GERAL]
    dj_circ_id = COMPONENT_TYPE_TO_YOLO_CLASS_ID[ComponentType.DISJUNTOR_CIRCUITO]

    recall_idr = idx_to_recall.get(idr_id, 0.0)
    recall_dps = idx_to_recall.get(dps_id, 0.0)

    dj_recalls = [
        idx_to_recall[cid] for cid in (dj_geral_id, dj_circ_id) if cid in idx_to_recall
    ]
    recall_disjuntor = min(dj_recalls) if dj_recalls else 0.0

    per_class = {
        ctype.value: round(idx_to_recall.get(cid, 0.0), 4)
        for ctype, cid in COMPONENT_TYPE_TO_YOLO_CLASS_ID.items()
    }

    return GoldenEvaluationMetrics(
        map50=round(map50, 4),
        map50_95=round(map50_95, 4),
        recall_idr=round(recall_idr, 4),
        recall_dps=round(recall_dps, 4),
        recall_disjuntor=round(recall_disjuntor, 4),
        per_class_recall=per_class,
    )
