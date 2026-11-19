"""Architectural-base-conditioned Electrical Floor Plan (Planta Elétrica .DXF) overlay generator.

GUARDRAIL:
Planta Elétrica (.DXF) MUST ONLY be generated over a user-uploaded architectural base .DXF
with valid spatial calibration. Never hallucinate floor plan geometry from scratch.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import ezdxf

from app.schemas.digital_twin import DigitalTwinJSON
from app.services.cad_engine.dxf_auditor import DXFAuditResult, save_audited_dxf_atomically


class PlantaOverlayPreconditionError(ValueError):
    """Raised when Planta Elétrica DXF export is requested without a base architectural DXF."""


@dataclass(frozen=True, slots=True)
class PlantaOverlayResult:
    dxf_path: Path
    dxf_audit: DXFAuditResult
    placed_points: int


def generate_planta_overlay_dxf(
    digital_twin: DigitalTwinJSON,
    destination: Path,
    base_dir: Path | None = None,
    require_human_calibration: bool = True,
) -> PlantaOverlayResult:
    """Overlay panel and calibrated circuit points onto a user-supplied architectural base .DXF."""
    calibration = digital_twin.spatial_calibration
    if calibration is None:
        raise PlantaOverlayPreconditionError(
            "Planta Elétrica (.DXF) requires an architectural base DXF and SpatialCalibration."
        )
    if require_human_calibration and not calibration.calibrated_by_human:
        raise PlantaOverlayPreconditionError(
            "SpatialCalibration must be explicitly confirmed by the engineer before Planta DXF export."
        )

    base_dxf = Path(calibration.base_dxf_path)
    if not base_dxf.exists():
        raise PlantaOverlayPreconditionError(
            f"Architectural base DXF not found on disk: '{base_dxf}'."
        )

    doc = ezdxf.readfile(str(base_dxf))
    msp = doc.modelspace()

    for layer_name, color in (
        ("EV_ELETRICA_QUADRO", 1),
        ("EV_ELETRICA_PONTOS", 5),
        ("EV_ELETRICA_ELETRODUTOS", 3),
        ("EV_ELETRICA_TEXTO", 7),
    ):
        if layer_name not in doc.layers:
            doc.layers.add(layer_name, color=color)

    ox, oy = calibration.origin_x, calibration.origin_y
    # Draw panel location symbol at calibrated origin
    msp.add_lwpolyline(
        [
            (ox - 0.3, oy - 0.15),
            (ox + 0.3, oy - 0.15),
            (ox + 0.3, oy + 0.15),
            (ox - 0.3, oy + 0.15),
            (ox - 0.3, oy - 0.15),
        ],
        dxfattribs={"layer": "EV_ELETRICA_QUADRO"},
    )
    msp.add_text(
        digital_twin.panel.panel_id,
        height=0.25,
        dxfattribs={"layer": "EV_ELETRICA_TEXTO", "insert": (ox + 0.35, oy)},
    )

    placed = 0
    for circ in digital_twin.circuits:
        if circ.plan_x_m is None or circ.plan_y_m is None:
            continue
        px, py = circ.plan_x_m, circ.plan_y_m
        # Conduit line from panel to circuit point
        msp.add_line((ox, oy), (px, py), dxfattribs={"layer": "EV_ELETRICA_ELETRODUTOS"})
        # Point symbol
        msp.add_circle((px, py), radius=0.18, dxfattribs={"layer": "EV_ELETRICA_PONTOS"})
        msp.add_text(
            f"{circ.circuit_id} ({circ.cable_phase_mm2:.1f}mm2)",
            height=0.20,
            dxfattribs={"layer": "EV_ELETRICA_TEXTO", "insert": (px + 0.22, py + 0.1)},
        )
        placed += 1

    saved_path, audit_res = save_audited_dxf_atomically(doc, destination, base_dir=base_dir)
    return PlantaOverlayResult(dxf_path=saved_path, dxf_audit=audit_res, placed_points=placed)
