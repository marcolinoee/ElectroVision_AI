"""Mandatory ezdxf.audit() gatekeeper and atomic .DXF writer."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ezdxf.document import Drawing

from app.core.storage import ensure_within_base


class DXFAuditError(ValueError):
    """Raised when a generated DXF document fails ezdxf.audit() with errors."""


@dataclass(frozen=True, slots=True)
class DXFAuditResult:
    """Result of running ezdxf.audit() on a CAD document."""

    passed: bool
    error_count: int
    fixes_count: int
    errors: list[str]


def audit_dxf_document(doc: Drawing) -> DXFAuditResult:
    """Run ezdxf.audit() and return structured error/fix diagnostics."""
    auditor = doc.audit()
    error_messages = [str(err) for err in auditor.errors]
    return DXFAuditResult(
        passed=len(error_messages) == 0,
        error_count=len(error_messages),
        fixes_count=len(auditor.fixes),
        errors=error_messages,
    )


def save_audited_dxf_atomically(
    doc: Drawing,
    destination: Path,
    base_dir: Path | None = None,
) -> tuple[Path, DXFAuditResult]:
    """Audit a DXF Drawing with ezdxf.audit() and save atomically (.tmp -> os.replace).

    GUARDRAIL: Refuses to save if `auditor.errors` is non-empty.
    """
    audit_res = audit_dxf_document(doc)
    if not audit_res.passed:
        raise DXFAuditError(
            f"DXF failed ezdxf.audit() with {audit_res.error_count} error(s): "
            f"{'; '.join(audit_res.errors[:5])}"
        )

    target = ensure_within_base(base_dir, destination) if base_dir is not None else destination
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".dxf.tmp",
        dir=str(target.parent),
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        doc.saveas(str(tmp_path))
        os.replace(tmp_path, target)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise

    return target, audit_res
