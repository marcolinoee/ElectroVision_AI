"""Server-Sent Events (SSE) endpoint streaming Celery job progress from Redis Pub/Sub."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.core.sse import subscribe_job_events

router = APIRouter(tags=["events"])


@router.get("/events/jobs/{job_id}")
async def stream_job_progress(job_id: str) -> EventSourceResponse:
    """Stream real-time JSON progress events for a Celery background job."""

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        async for event in subscribe_job_events(job_id):
            yield {
                "event": event.get("status", "PROGRESS").lower(),
                "data": json.dumps(event, ensure_ascii=False),
            }

    return EventSourceResponse(event_generator())
