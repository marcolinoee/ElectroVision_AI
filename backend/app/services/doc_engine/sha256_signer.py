"""SHA-256 audit manifest signer binding validated DigitalTwinJSON to exported artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.security import compute_sha256_file
from app.core.storage import atomic_write_text
from app.models.enums import ArtifactType


@dataclass(frozen=True, slots=True)
class SignedArtifactRecord:
    artifact_type: ArtifactType
    filename: str
    path: Path
    sha256: str
    size_bytes: int


def write_export_audit_manifest(
    export_dir: Path,
    inspection_id: str,
    digital_twin_sha256: str,
    engineer_name: str,
    engineer_crea: str,
    art_number: str | None,
    artifacts: list[tuple[ArtifactType, Path]],
    base_dir: Path | None = None,
) -> tuple[Path, list[SignedArtifactRecord]]:
    """Compute SHA-256 for every exported artifact and write atomic `export_manifest.json`."""
    records: list[SignedArtifactRecord] = []
    for art_type, art_path in artifacts:
        if not art_path.exists():
            raise FileNotFoundError(f"Cannot sign missing artifact: {art_path}")
        records.append(
            SignedArtifactRecord(
                artifact_type=art_type,
                filename=art_path.name,
                path=art_path,
                sha256=compute_sha256_file(art_path),
                size_bytes=art_path.stat().st_size,
            )
        )

    manifest_payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "inspection_id": inspection_id,
        "digital_twin_sha256": digital_twin_sha256,
        "engineer_sign_off": {
            "name": engineer_name,
            "crea": engineer_crea,
            "art_number": art_number,
        },
        "generated_at": datetime.now(UTC).isoformat(),
        "artifacts": [
            {
                "artifact_type": rec.artifact_type.value,
                "filename": rec.filename,
                "sha256": rec.sha256,
                "size_bytes": rec.size_bytes,
            }
            for rec in records
        ],
    }

    manifest_path = export_dir / "export_manifest.json"
    atomic_write_text(
        manifest_path,
        json.dumps(manifest_payload, indent=2, ensure_ascii=False),
        base_dir=base_dir,
    )
    return manifest_path, records


def verify_export_manifest(manifest_path: Path) -> tuple[bool, list[str]]:
    """Independently verify that every file in `export_manifest.json` matches its recorded SHA-256."""
    if not manifest_path.exists():
        return False, ["Manifest file does not exist."]

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    export_dir = manifest_path.parent
    errors: list[str] = []

    for entry in data.get("artifacts", []):
        file_path = export_dir / entry["filename"]
        if not file_path.exists():
            errors.append(f"Missing artifact: {entry['filename']}")
            continue
        actual_sha = compute_sha256_file(file_path)
        if actual_sha != entry["sha256"]:
            errors.append(
                f"SHA-256 mismatch for {entry['filename']}: expected {entry['sha256']}, got {actual_sha}"
            )

    return len(errors) == 0, errors
