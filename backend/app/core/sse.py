"""Redis Pub/Sub helpers for Server-Sent Events (SSE) Celery job progress streaming."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import redis as sync_redis
import redis.asyncio as async_redis

from app.core.config import get_settings


def job_channel_name(job_id: str) -> str:
    return f"electrovision:job:{job_id}"


def publish_job_event(
    job_id: str,
    status: str,
    progress_pct: int,
    message: str,
    payload: dict[str, Any] | None = None,
    redis_url: str | None = None,
) -> None:
    """Synchronous publisher used inside Celery workers to emit job progress."""
    url = redis_url or get_settings().redis_url
    event = {
        "job_id": job_id,
        "status": status,
        "progress_pct": max(0, min(100, progress_pct)),
        "message": message,
        "payload": payload or {},
        "timestamp": datetime.now(UTC).isoformat(),
    }
    client = sync_redis.Redis.from_url(url, decode_responses=True)
    try:
        client.publish(job_channel_name(job_id), json.dumps(event, ensure_ascii=False))
    finally:
        client.close()


async def subscribe_job_events(
    job_id: str,
    redis_url: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Async generator yielding SSE job progress events from Redis Pub/Sub."""
    url = redis_url or get_settings().redis_url
    client = async_redis.from_url(url, decode_responses=True)
    pubsub = client.pubsub()
    channel = job_channel_name(job_id)
    await pubsub.subscribe(channel)
    try:
        async for raw_message in pubsub.listen():
            if raw_message.get("type") != "message":
                continue
            data = json.loads(raw_message["data"])
            yield data
            if data.get("status") in {"COMPLETED", "FAILED"}:
                break
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await client.aclose()
