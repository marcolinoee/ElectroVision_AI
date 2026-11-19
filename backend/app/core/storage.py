"""Atomic filesystem writes (.tmp -> fsync -> os.replace) and safe storage path utilities."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


class PathTraversalError(ValueError):
    """Raised when a requested path attempts to escape the allowed storage root."""


def ensure_within_base(base_dir: Path, target_path: Path) -> Path:
    """Resolve target_path and verify it is strictly contained within base_dir.

    Prevents path traversal (`..`), null-byte injection, and symlink escapes.
    """
    raw_str = str(target_path)
    if "\x00" in raw_str:
        raise PathTraversalError("Null byte detected in path.")

    resolved_base = base_dir.resolve()
    candidate = (
        (resolved_base / target_path).resolve()
        if not target_path.is_absolute()
        else target_path.resolve()
    )

    try:
        candidate.relative_to(resolved_base)
    except ValueError as exc:
        raise PathTraversalError(
            f"Path '{target_path}' escapes allowed storage root '{resolved_base}'."
        ) from exc

    return candidate


def atomic_write_bytes(destination: Path, data: bytes, base_dir: Path | None = None) -> Path:
    """Write bytes atomically using a sibling temporary file, fsync, and os.replace."""
    target = ensure_within_base(base_dir, destination) if base_dir is not None else destination
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise

    return target


def atomic_write_text(
    destination: Path,
    text: str,
    encoding: str = "utf-8",
    base_dir: Path | None = None,
) -> Path:
    """Write UTF-8 text atomically via .tmp -> fsync -> os.replace."""
    return atomic_write_bytes(destination, text.encode(encoding), base_dir=base_dir)


def atomic_replace_file(source_tmp: Path, destination: Path, base_dir: Path | None = None) -> Path:
    """Atomically promote an already-written temporary file (e.g. .pt, .dxf, .docx, .xlsx)."""
    target = ensure_within_base(base_dir, destination) if base_dir is not None else destination
    if not source_tmp.exists():
        raise FileNotFoundError(f"Temporary source file does not exist: {source_tmp}")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source_tmp, target)
    return target
