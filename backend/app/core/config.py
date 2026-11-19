"""Application configuration via Pydantic Settings (100% local-first)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed environment settings for API and Celery workers."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    electrovision_env: Literal["development", "production", "test"] = "development"
    electrovision_log_level: str = "INFO"
    electrovision_confidence_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    electrovision_device: Literal["cpu", "cuda"] = "cpu"

    # Database (PostgreSQL 16 + pgvector)
    database_url: str = (
        "postgresql+asyncpg://electrovision:electrovision_local_secret@localhost:5432/electrovision"
    )
    database_sync_url: str = (
        "postgresql+psycopg://electrovision:electrovision_local_secret@localhost:5432/electrovision"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Redis & Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Storage
    storage_root: Path = Path("/app/storage")

    # AppSec Upload Limits
    max_image_upload_mb: int = Field(default=25, ge=1, le=200)
    max_video_upload_mb: int = Field(default=250, ge=1, le=2048)
    max_dxf_upload_mb: int = Field(default=50, ge=1, le=500)
    max_pdf_upload_mb: int = Field(default=100, ge=1, le=500)
    max_image_pixels: int = Field(default=40_000_000, ge=1_000_000)

    # CORS
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3030",
            "http://127.0.0.1:3030",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def uploads_dir(self) -> Path:
        return self.storage_root / "uploads"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def proxies_dir(self) -> Path:
        return self.storage_root / "proxies"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def frames_dir(self) -> Path:
        return self.storage_root / "frames"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def datasets_dir(self) -> Path:
        return self.storage_root / "datasets"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def golden_set_dir(self) -> Path:
        return self.storage_root / "golden_set"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def models_weights_dir(self) -> Path:
        return self.storage_root / "models_weights"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def exports_dir(self) -> Path:
        return self.storage_root / "exports"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def norms_pdfs_dir(self) -> Path:
        return self.storage_root / "norms_pdfs"

    def ensure_storage_directories(self) -> None:
        """Create all required local storage directories idempotently."""
        for directory in (
            self.uploads_dir,
            self.proxies_dir,
            self.frames_dir,
            self.datasets_dir,
            self.golden_set_dir,
            self.models_weights_dir,
            self.exports_dir,
            self.norms_pdfs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
