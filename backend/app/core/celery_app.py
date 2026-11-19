"""Celery application with strict queue isolation: vision_queue, train_queue, engine_queue."""

from celery import Celery
from kombu import Queue

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "electrovision",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_queues=(
        Queue("vision_queue"),
        Queue("train_queue"),
        Queue("engine_queue"),
    ),
    task_default_queue="engine_queue",
    task_routes={
        "app.services.vision.*": {"queue": "vision_queue"},
        "app.services.ml_ops.*": {"queue": "train_queue"},
        "app.services.compliance.*": {"queue": "engine_queue"},
        "app.services.cad_engine.*": {"queue": "engine_queue"},
        "app.services.doc_engine.*": {"queue": "engine_queue"},
    },
)
