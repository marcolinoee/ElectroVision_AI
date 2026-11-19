"""Active Learning YOLO fine-tuning pipeline & Celery task (`train_queue`)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import select

from app.core.celery_app import celery_app
from app.core.config import Settings, get_settings
from app.core.database import build_sync_session_factory
from app.core.logging import get_logger
from app.core.sse import publish_job_event
from app.models.audit_log import AuditLog
from app.models.dataset_sample import DatasetSample, ModelVersion
from app.models.enums import DatasetSplit
from app.services.ml_ops.atomic_registry import AtomicModelRegistry, RegisteredWeights
from app.services.ml_ops.dataset_builder import SampleRecord, build_active_learning_dataset
from app.services.ml_ops.golden_set_eval import (
    GoldenEvaluationMetrics,
    PromotionDecision,
    evaluate_promotion_gate,
    run_yolo_golden_evaluation,
)

logger = get_logger(__name__)


class TrainerBackendProtocol(Protocol):
    """Protocol for YOLO training + Golden Holdout evaluation (injectable in unit tests)."""

    def train(
        self,
        base_weights: Path,
        data_yaml: Path,
        output_run_dir: Path,
        epochs: int,
        device: str,
    ) -> Path:
        """Train candidate model and return path to `best.pt`."""
        ...

    def evaluate_golden(
        self,
        weights_path: Path,
        data_yaml: Path,
        device: str,
    ) -> GoldenEvaluationMetrics:
        """Evaluate candidate weights on locked Golden Holdout Set."""
        ...


class UltralyticsTrainerBackend:
    """Production local YOLO trainer executed inside `worker-ml` (`train_queue`)."""

    def train(
        self,
        base_weights: Path,
        data_yaml: Path,
        output_run_dir: Path,
        epochs: int,
        device: str,
    ) -> Path:
        from ultralytics import YOLO  # Lazy import isolated to worker-ml

        model = YOLO(str(base_weights))
        model.train(
            data=str(data_yaml),
            epochs=epochs,
            device=device,
            project=str(output_run_dir),
            name="active_learning_run",
            exist_ok=True,
            verbose=False,
        )
        best_pt = output_run_dir / "active_learning_run" / "weights" / "best.pt"
        if not best_pt.exists():
            raise FileNotFoundError(f"Training completed without producing best.pt at {best_pt}")
        return best_pt

    def evaluate_golden(
        self,
        weights_path: Path,
        data_yaml: Path,
        device: str,
    ) -> GoldenEvaluationMetrics:
        return run_yolo_golden_evaluation(weights_path, data_yaml, device=device)


@dataclass(frozen=True, slots=True)
class ActiveLearningRunResult:
    """Complete result of an Active Learning training + Golden Holdout gatekeeper run."""

    version_tag: str
    decision: PromotionDecision
    registered: RegisteredWeights


def run_active_learning_cycle(
    base_weights: Path,
    data_yaml: Path,
    baseline_map50_95: float,
    version_tag: str,
    models_dir: Path,
    run_output_dir: Path,
    backend: TrainerBackendProtocol,
    epochs: int = 20,
    device: str = "cpu",
    base_dir: Path | None = None,
) -> ActiveLearningRunResult:
    """Train candidate YOLO model, evaluate on Golden Holdout Set, and atomically promote iff approved."""
    candidate_pt = backend.train(
        base_weights=base_weights,
        data_yaml=data_yaml,
        output_run_dir=run_output_dir,
        epochs=epochs,
        device=device,
    )
    metrics = backend.evaluate_golden(
        weights_path=candidate_pt,
        data_yaml=data_yaml,
        device=device,
    )
    decision = evaluate_promotion_gate(
        candidate=metrics,
        baseline_map50_95=baseline_map50_95,
    )

    registry = AtomicModelRegistry(models_dir=models_dir, base_dir=base_dir)
    registered = registry.register_candidate(
        candidate_pt_path=candidate_pt,
        version_tag=version_tag,
        promote=decision.approved,
        metrics={
            "map50": metrics.map50,
            "map50_95": metrics.map50_95,
            "recall_idr": metrics.recall_idr,
            "recall_dps": metrics.recall_dps,
            "recall_disjuntor": metrics.recall_disjuntor,
            "reasons": decision.reasons,
        },
    )
    return ActiveLearningRunResult(
        version_tag=version_tag,
        decision=decision,
        registered=registered,
    )


@celery_app.task(name="app.services.ml_ops.yolo_trainer.run_active_learning_train_task", bind=True)
def run_active_learning_train_task(
    self: Any,
    epochs: int = 20,
    replay_ratio: float = 0.5,
) -> dict[str, Any]:
    """Celery task executed on isolated `worker-ml` (`train_queue`)."""
    job_id = str(self.request.id or "active-learning")
    settings: Settings = get_settings()
    settings.ensure_storage_directories()
    session_factory = build_sync_session_factory()

    publish_job_event(job_id, "STARTED", 5, "Preparando dataset Active Learning + Replay Buffer...")

    with session_factory() as session:
        try:
            all_samples = list(session.scalars(select(DatasetSample)).all())
            human_records = [
                SampleRecord(
                    image_path=Path(s.image_path),
                    label_path=Path(s.label_path),
                    split=s.split,
                    source=s.source,
                    is_locked_golden=s.is_locked_golden,
                )
                for s in all_samples
                if s.source == "human_correction" and not s.is_locked_golden
            ]
            replay_records = [
                SampleRecord(
                    image_path=Path(s.image_path),
                    label_path=Path(s.label_path),
                    split=s.split,
                    source=s.source,
                    is_locked_golden=s.is_locked_golden,
                )
                for s in all_samples
                if s.source != "human_correction"
                and s.split != DatasetSplit.GOLDEN_HOLDOUT
                and not s.is_locked_golden
            ]
            golden_records = [
                SampleRecord(
                    image_path=Path(s.image_path),
                    label_path=Path(s.label_path),
                    split=DatasetSplit.GOLDEN_HOLDOUT,
                    source=s.source,
                    is_locked_golden=True,
                )
                for s in all_samples
                if s.is_locked_golden or s.split == DatasetSplit.GOLDEN_HOLDOUT
            ]

            ts_tag = datetime.now(UTC).strftime("v%Y%m%d_%H%M%S")
            dataset_dir = settings.datasets_dir / f"run_{ts_tag}"
            bundle = build_active_learning_dataset(
                human_corrections=human_records,
                replay_buffer=replay_records,
                golden_holdout=golden_records,
                output_dataset_dir=dataset_dir,
                replay_ratio=replay_ratio,
                base_dir=settings.storage_root,
            )

            active_model = session.scalar(
                select(ModelVersion).where(ModelVersion.is_active.is_(True))
            )
            baseline_map50_95 = active_model.map50_95 if active_model is not None else 0.0
            base_weights = (
                Path(active_model.weights_path)
                if active_model is not None and Path(active_model.weights_path).exists()
                else settings.models_weights_dir / "active.pt"
            )

            publish_job_event(
                job_id,
                "PROGRESS",
                35,
                f"Treinando YOLO ({epochs} épocas) em {settings.electrovision_device}...",
                {"train_count": bundle.train_count, "replay_count": bundle.replay_count},
            )

            run_result = run_active_learning_cycle(
                base_weights=base_weights,
                data_yaml=bundle.data_yaml_path,
                baseline_map50_95=baseline_map50_95,
                version_tag=ts_tag,
                models_dir=settings.models_weights_dir,
                run_output_dir=dataset_dir / "runs",
                backend=UltralyticsTrainerBackend(),
                epochs=epochs,
                device=settings.electrovision_device,
                base_dir=settings.storage_root,
            )

            publish_job_event(job_id, "PROGRESS", 85, "Registrando versão e auditoria MLOps...")
            if run_result.decision.approved and active_model is not None:
                active_model.is_active = False

            new_version = ModelVersion(
                version_tag=run_result.version_tag,
                weights_path=str(run_result.registered.versioned_path),
                weights_sha256=run_result.registered.sha256,
                map50=run_result.decision.candidate_metrics.map50,
                map50_95=run_result.decision.candidate_metrics.map50_95,
                critical_recall_idr=run_result.decision.candidate_metrics.recall_idr,
                critical_recall_dps=run_result.decision.candidate_metrics.recall_dps,
                critical_recall_disjuntor=run_result.decision.candidate_metrics.recall_disjuntor,
                is_active=run_result.decision.approved,
                promoted_at=datetime.now(UTC) if run_result.decision.approved else None,
                metrics_json={
                    "reasons": run_result.decision.reasons,
                    "per_class_recall": run_result.decision.candidate_metrics.per_class_recall,
                },
            )
            session.add(new_version)
            session.add(
                AuditLog(
                    event_type=(
                        "MODEL_PROMOTED" if run_result.decision.approved else "MODEL_REJECTED"
                    ),
                    artifact_path=str(run_result.registered.versioned_path),
                    artifact_sha256=run_result.registered.sha256,
                    details_json={
                        "version_tag": run_result.version_tag,
                        "approved": run_result.decision.approved,
                        "reasons": run_result.decision.reasons,
                        "map50_95": run_result.decision.candidate_metrics.map50_95,
                        "baseline_map50_95": baseline_map50_95,
                    },
                )
            )
            session.commit()

            payload = {
                "version_tag": run_result.version_tag,
                "approved": run_result.decision.approved,
                "reasons": run_result.decision.reasons,
                "map50_95": run_result.decision.candidate_metrics.map50_95,
            }
            publish_job_event(
                job_id,
                "COMPLETED",
                100,
                "Treinamento e avaliação Golden Holdout concluídos.",
                payload,
            )
            return payload
        except Exception as exc:
            session.rollback()
            logger.exception("active_learning_failed", error=str(exc))
            publish_job_event(job_id, "FAILED", 100, f"Erro no treinamento Active Learning: {exc}")
            raise
