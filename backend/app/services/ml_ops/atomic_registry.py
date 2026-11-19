"""Atomic YOLO .pt Model Registry (.tmp -> fsync -> os.replace) with SHA-256 verification."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.security import compute_sha256_file
from app.core.storage import atomic_write_bytes, atomic_write_text, ensure_within_base


@dataclass(frozen=True, slots=True)
class RegisteredWeights:
    """Immutable record of a registered & atomically stored .pt model."""

    version_tag: str
    versioned_path: Path
    active_path: Path | None
    sha256: str
    promoted: bool


class AtomicModelRegistry:
    """Manages immutable versioned .pt weights and atomic active.pt promotion/rollback."""

    def __init__(self, models_dir: Path, base_dir: Path | None = None) -> None:
        self._models_dir = models_dir
        self._versions_dir = models_dir / "versions"
        self._active_path = models_dir / "active.pt"
        self._manifest_path = models_dir / "active_manifest.json"
        self._base_dir = base_dir
        self._versions_dir.mkdir(parents=True, exist_ok=True)

    @property
    def active_weights_path(self) -> Path:
        return self._active_path

    def register_candidate(
        self,
        candidate_pt_path: Path,
        version_tag: str,
        promote: bool,
        metrics: dict[str, Any] | None = None,
    ) -> RegisteredWeights:
        """Atomically archive candidate weights and optionally promote to active.pt."""
        if not candidate_pt_path.exists():
            raise FileNotFoundError(f"Candidate .pt weights not found: {candidate_pt_path}")

        safe_tag = "".join(ch for ch in version_tag if ch.isalnum() or ch in {"-", "_", "."})
        if not safe_tag:
            raise ValueError("Invalid version_tag.")

        raw_bytes = candidate_pt_path.read_bytes()
        if not raw_bytes:
            raise ValueError("Candidate .pt file is empty.")

        versioned_dest = self._versions_dir / f"{safe_tag}.pt"
        if self._base_dir is not None:
            versioned_dest = ensure_within_base(self._base_dir, versioned_dest)

        atomic_write_bytes(versioned_dest, raw_bytes, base_dir=self._base_dir)
        digest = compute_sha256_file(versioned_dest)

        active_dest: Path | None = None
        if promote:
            active_dest = self._promote_bytes(
                raw_bytes=raw_bytes,
                version_tag=safe_tag,
                versioned_path=versioned_dest,
                sha256=digest,
                metrics=metrics or {},
            )

        return RegisteredWeights(
            version_tag=safe_tag,
            versioned_path=versioned_dest,
            active_path=active_dest,
            sha256=digest,
            promoted=promote,
        )

    def rollback_to_version(self, version_tag: str) -> RegisteredWeights:
        """Atomically roll back active.pt to a previously archived version."""
        versioned_path = self._versions_dir / f"{version_tag}.pt"
        if not versioned_path.exists():
            raise FileNotFoundError(f"Version '{version_tag}' not found in registry.")

        raw_bytes = versioned_path.read_bytes()
        digest = compute_sha256_file(versioned_path)
        active_dest = self._promote_bytes(
            raw_bytes=raw_bytes,
            version_tag=version_tag,
            versioned_path=versioned_path,
            sha256=digest,
            metrics={"rollback": True},
        )
        return RegisteredWeights(
            version_tag=version_tag,
            versioned_path=versioned_path,
            active_path=active_dest,
            sha256=digest,
            promoted=True,
        )

    def read_active_manifest(self) -> dict[str, Any] | None:
        if not self._manifest_path.exists():
            return None
        return json.loads(self._manifest_path.read_text(encoding="utf-8"))

    def _promote_bytes(
        self,
        raw_bytes: bytes,
        version_tag: str,
        versioned_path: Path,
        sha256: str,
        metrics: dict[str, Any],
    ) -> Path:
        atomic_write_bytes(self._active_path, raw_bytes, base_dir=self._base_dir)
        manifest = {
            "version_tag": version_tag,
            "versioned_path": str(versioned_path),
            "active_path": str(self._active_path),
            "sha256": sha256,
            "promoted_at": datetime.now(UTC).isoformat(),
            "metrics": metrics,
        }
        atomic_write_text(
            self._manifest_path,
            json.dumps(manifest, indent=2, ensure_ascii=False),
            base_dir=self._base_dir,
        )
        return self._active_path
