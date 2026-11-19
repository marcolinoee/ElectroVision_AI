"""FastAPI application entrypoint for ElectroVision AI."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1 import events, export, inference, ml_train, projects, upload, validation
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.schemas.api import HealthResponse

settings = get_settings()
configure_logging(
    log_level=settings.electrovision_log_level,
    json_logs=settings.electrovision_env == "production",
)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings.ensure_storage_directories()
    logger.info(
        "electrovision_api_startup",
        version=__version__,
        env=settings.electrovision_env,
        device=settings.electrovision_device,
    )
    yield
    logger.info("electrovision_api_shutdown")


app = FastAPI(
    title="ElectroVision AI API",
    version=__version__,
    description="Local-first Diagnostic Electrical Engineering & Computer Vision Platform",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api/v1")
app.include_router(upload.router, prefix="/api/v1")
app.include_router(inference.router, prefix="/api/v1")
app.include_router(validation.router, prefix="/api/v1")
app.include_router(export.router, prefix="/api/v1")
app.include_router(ml_train.router, prefix="/api/v1")
app.include_router(events.router, prefix="/api/v1")


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def healthcheck() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.electrovision_env,
        device=settings.electrovision_device,
    )
