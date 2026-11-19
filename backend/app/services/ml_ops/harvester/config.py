"""Pydantic v2 configuration for the Public Electrical Dataset Harvester."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import get_settings

# Hard non-negotiable 950 MB usable cap (strictly below 1 GB = 1,073,741,824 bytes)
HARD_QUOTA_BYTES: int = 996_147_200


class HarvesterConfig(BaseSettings):
    """Typed runtime settings for public dataset harvesting."""

    model_config = SettingsConfigDict(
        env_prefix="HARVESTER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    max_bytes: int = Field(default=HARD_QUOTA_BYTES, ge=1_048_576, le=HARD_QUOTA_BYTES)
    min_width: int = Field(default=320, ge=64)
    min_height: int = Field(default=320, ge=64)
    wikimedia_min_width: int = Field(default=640, ge=320)
    wikimedia_min_height: int = Field(default=480, ge=240)
    max_dimension: int = Field(default=1280, ge=320, le=2048)
    jpeg_quality: int = Field(default=85, ge=50, le=95)
    blur_threshold: float = Field(default=50.0, ge=0.0)
    phash_hamming_threshold: int = Field(default=5, ge=0, le=32)

    http_timeout_s: float = Field(default=20.0, gt=1.0)
    max_retries: int = Field(default=4, ge=1, le=10)
    backoff_base_s: float = Field(default=1.0, gt=0.1)
    user_agent: str = (
        "ElectroVisionAI-DatasetHarvester/1.0 "
        "(https://github.com/marcolinoee/ElectroVision_AI; open-data-research)"
    )

    train_ratio: float = Field(default=0.70, gt=0.0, lt=1.0)
    val_ratio: float = Field(default=0.15, gt=0.0, lt=1.0)
    golden_test_ratio: float = Field(default=0.15, gt=0.0, lt=1.0)
    random_seed: int = 42

    max_items_per_source: int = Field(default=1500, ge=1)
    output_dir: Path = Field(
        default_factory=lambda: get_settings().datasets_dir / "public_harvest"
    )
    taxonomy_path: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent / "taxonomy.yaml"
    )
    enabled_sources: list[str] = Field(
        default_factory=lambda: ["wikimedia", "huggingface", "public_yolo", "cad_symbols"]
    )
    public_yolo_manifest_path: Path | None = None
    cad_symbols_manifest_path: Path | None = None
