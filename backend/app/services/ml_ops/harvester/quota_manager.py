"""Thread-safe DiskQuotaManager enforcing a strict hard cap (default 950 MB / 996,147,200 bytes)."""

from __future__ import annotations

import threading
from pathlib import Path

from app.core.storage import atomic_write_bytes, atomic_write_text, ensure_within_base
from app.services.ml_ops.harvester.config import HARD_QUOTA_BYTES


class QuotaExceededError(RuntimeError):
    """Raised when an allocation would exceed the configured disk quota."""


class DiskQuotaManager:
    """Thread-safe byte accounting & atomic disk writer with hard quota enforcement."""

    def __init__(self, root_dir: Path, max_bytes: int = HARD_QUOTA_BYTES) -> None:
        if max_bytes <= 0 or max_bytes > HARD_QUOTA_BYTES:
            raise ValueError(
                f"max_bytes must be between 1 and {HARD_QUOTA_BYTES} (950 MB), got {max_bytes}."
            )
        self._root_dir = root_dir.resolve()
        self._root_dir.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        self._used_bytes = self._scan_existing_bytes()

    def _scan_existing_bytes(self) -> int:
        total = 0
        for path in self._root_dir.rglob("*"):
            if path.is_file():
                total += path.stat().st_size
        return total

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def used_bytes(self) -> int:
        with self._lock:
            return self._used_bytes

    @property
    def remaining_bytes(self) -> int:
        with self._lock:
            return max(0, self._max_bytes - self._used_bytes)

    @property
    def is_exhausted(self) -> bool:
        with self._lock:
            return self._used_bytes >= self._max_bytes

    @property
    def utilization_pct(self) -> float:
        with self._lock:
            return round((self._used_bytes / self._max_bytes) * 100.0, 2)

    def can_allocate(self, num_bytes: int) -> bool:
        if num_bytes < 0:
            raise ValueError("num_bytes must be non-negative.")
        with self._lock:
            return (self._used_bytes + num_bytes) <= self._max_bytes

    def reserve(self, num_bytes: int) -> None:
        """Atomically reserve bytes or raise QuotaExceededError before touching disk."""
        if num_bytes < 0:
            raise ValueError("num_bytes must be non-negative.")
        with self._lock:
            if self._used_bytes + num_bytes > self._max_bytes:
                raise QuotaExceededError(
                    f"Disk quota reached: used={self._used_bytes} + requested={num_bytes} "
                    f"> max_bytes={self._max_bytes}."
                )
            self._used_bytes += num_bytes

    def release(self, num_bytes: int) -> None:
        """Return previously reserved bytes if a write is rolled back."""
        if num_bytes <= 0:
            return
        with self._lock:
            self._used_bytes = max(0, self._used_bytes - num_bytes)

    def write_bytes(self, destination: Path, data: bytes) -> Path:
        """Reserve quota and atomically write bytes inside root_dir."""
        target = ensure_within_base(self._root_dir, destination)
        previous_size = target.stat().st_size if target.exists() else 0
        delta = max(0, len(data) - previous_size)
        self.reserve(delta)
        try:
            atomic_write_bytes(target, data, base_dir=self._root_dir)
            if len(data) < previous_size:
                self.release(previous_size - len(data))
            return target
        except Exception:
            self.release(delta)
            raise

    def write_text(self, destination: Path, text: str, encoding: str = "utf-8") -> Path:
        """Reserve quota and atomically write UTF-8 text inside root_dir."""
        encoded = text.encode(encoding)
        return self.write_bytes(destination, encoded)

    def write_metadata_unchecked(self, destination: Path, text: str) -> Path:
        """Write final manifest.json / dataset.yaml during graceful shutdown (small metadata)."""
        target = ensure_within_base(self._root_dir, destination)
        return atomic_write_text(target, text, base_dir=self._root_dir)
