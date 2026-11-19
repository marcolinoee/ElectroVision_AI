"""Deterministic Single-Line Diagram (Diagrama Unifilar) generator in .DXF and .SVG."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path

import ezdxf

from app.core.storage import atomic_write_text
from app.models.enums import ComponentType
from app.schemas.digital_twin import DigitalTwinJSON, PanelComponent
from app.services.cad_engine.dxf_auditor import DXFAuditResult, save_audited_dxf_atomically


@dataclass(frozen=True, slots=True)
class UnifilarExportResult:
    """Generated Diagrama Unifilar artifacts."""

    dxf_path: Path
    svg_path: Path
    dxf_audit: DXFAuditResult


def _setup_unifilar_layers(doc: ezdxf.document.Drawing) -> None:
    layer_defs = [
        ("EV_QUADRO", 7),        # White/Black outline
        ("EV_BARRAMENTOS", 1),   # Red main busbar
        ("EV_PROTECAO", 3),      # Green protection devices
        ("EV_CIRCUITOS", 5),     # Blue outgoing circuits
        ("EV_TEXTO", 7),         # Labels
        ("EV_CARIMBO", 2),       # Yellow title block
    ]
    for name, color in layer_defs:
        if name not in doc.layers:
            doc.layers.add(name, color=color)


def _format_breaker_label(comp: PanelComponent | None) -> str:
    if comp is None:
        return "DJ N/I"
    curve = comp.trip_curve.value if comp.trip_curve else "C"
    amps = f"{int(comp.rated_current_a)}A" if comp.rated_current_a else "?A"
    poles = f"{comp.poles}P" if comp.poles else ""
    return f"{poles} {curve}{amps}".strip()


def generate_unifilar_dxf_and_svg(
    digital_twin: DigitalTwinJSON,
    dxf_destination: Path,
    svg_destination: Path,
    engineer_name: str,
    engineer_crea: str,
    art_number: str | None = None,
    base_dir: Path | None = None,
) -> UnifilarExportResult:
    """Generate an audited .DXF and matching .SVG Diagrama Unifilar from validated DigitalTwinJSON."""
    doc = ezdxf.new("R2010", setup=True)
    _setup_unifilar_layers(doc)
    msp = doc.modelspace()

    comp_map = {c.component_id: c for c in digital_twin.components}
    panel = digital_twin.panel
    twin_hash = digital_twin.canonical_sha256()

    circuits = digital_twin.circuits
    n_circuits = max(1, len(circuits))
    col_spacing = 45.0
    total_width = max(260.0, 90.0 + n_circuits * col_spacing)
    bus_y = 140.0
    start_x = 45.0
    end_x = start_x + (n_circuits - 1) * col_spacing if n_circuits > 1 else start_x + 120.0

    # 1. Panel enclosure frame
    msp.add_lwpolyline(
        [(10, 10), (total_width, 10), (total_width, 230), (10, 230), (10, 10)],
        dxfattribs={"layer": "EV_QUADRO"},
    )

    # 2. Incoming Feeder + Main Breaker + DPS + IDR on left/top
    feeder_x = start_x + (end_x - start_x) / 2.0
    msp.add_line((feeder_x, 215), (feeder_x, 185), dxfattribs={"layer": "EV_BARRAMENTOS"})
    msp.add_text(
        f"ALIMENTACAO: {panel.supply_system.value} ({panel.nominal_voltage_v:.0f}V) - {panel.grounding_scheme.value}",
        height=3.2,
        dxfattribs={"layer": "EV_TEXTO", "insert": (20, 218)},
    )

    # Main breaker symbol
    main_breaker = comp_map.get(panel.main_breaker_id) if panel.main_breaker_id else None
    msp.add_lwpolyline(
        [(feeder_x - 6, 173), (feeder_x + 6, 173), (feeder_x + 6, 185), (feeder_x - 6, 185), (feeder_x - 6, 173)],
        dxfattribs={"layer": "EV_PROTECAO"},
    )
    msp.add_line((feeder_x, 173), (feeder_x, bus_y), dxfattribs={"layer": "EV_BARRAMENTOS"})
    msp.add_text(
        f"DJ GERAL: {_format_breaker_label(main_breaker)}",
        height=2.8,
        dxfattribs={"layer": "EV_TEXTO", "insert": (feeder_x + 9, 177)},
    )

    # DPS branch if present
    dps_comps = [c for c in digital_twin.components if c.component_type == ComponentType.DPS]
    if panel.has_dps or dps_comps:
        dps_x = 25.0
        msp.add_line((dps_x, bus_y), (dps_x, 170), dxfattribs={"layer": "EV_PROTECAO"})
        msp.add_lwpolyline(
            [(dps_x - 5, 170), (dps_x + 5, 170), (dps_x + 5, 182), (dps_x - 5, 182), (dps_x - 5, 170)],
            dxfattribs={"layer": "EV_PROTECAO"},
        )
        msp.add_text("DPS", height=2.6, dxfattribs={"layer": "EV_TEXTO", "insert": (dps_x - 4, 184)})

    # 3. Main Horizontal Busbar
    msp.add_line((20.0, bus_y), (total_width - 15.0, bus_y), dxfattribs={"layer": "EV_BARRAMENTOS"})
    msp.add_text(
        f"BARRAMENTO PRINCIPAL - {panel.name}",
        height=2.8,
        dxfattribs={"layer": "EV_TEXTO", "insert": (22, bus_y + 3)},
    )

    # 4. Outgoing Circuits
    svg_circuits_markup: list[str] = []
    for idx, circ in enumerate(circuits):
        cx = start_x + idx * col_spacing
        breaker = comp_map.get(circ.breaker_component_id) if circ.breaker_component_id else None
        idr = comp_map.get(circ.idr_component_id) if circ.idr_component_id else None

        # Vertical drop from busbar
        msp.add_line((cx, bus_y), (cx, 118), dxfattribs={"layer": "EV_CIRCUITOS"})
        # Breaker box
        msp.add_lwpolyline(
            [(cx - 5, 106), (cx + 5, 106), (cx + 5, 118), (cx - 5, 118), (cx - 5, 106)],
            dxfattribs={"layer": "EV_PROTECAO"},
        )
        msp.add_line((cx, 106), (cx, 68), dxfattribs={"layer": "EV_CIRCUITOS"})

        # IDR indicator if associated
        if idr is not None:
            msp.add_circle((cx, 92), radius=4.0, dxfattribs={"layer": "EV_PROTECAO"})
            msp.add_text(
                f"IDR {idr.sensitivity_ma or 30}mA",
                height=2.0,
                dxfattribs={"layer": "EV_TEXTO", "insert": (cx + 5, 91)},
            )

        # Annotations
        msp.add_text(
            circ.circuit_id,
            height=2.6,
            dxfattribs={"layer": "EV_TEXTO", "insert": (cx - 8, 62)},
        )
        msp.add_text(
            _format_breaker_label(breaker),
            height=2.2,
            dxfattribs={"layer": "EV_TEXTO", "insert": (cx - 10, 56)},
        )
        msp.add_text(
            f"{circ.cable_phase_mm2:.1f}mm2 | {circ.load_power_va:.0f}VA",
            height=2.0,
            dxfattribs={"layer": "EV_TEXTO", "insert": (cx - 14, 50)},
        )

        # Matching SVG coordinates (Y flipped for SVG top-down space)
        svg_x = 60 + idx * 140
        svg_idr = (
            f'<circle cx="{svg_x}" cy="240" r="12" fill="none" stroke="#16a34a" stroke-width="2"/>'
            f'<text x="{svg_x + 16}" y="244" font-size="10" fill="#15803d">IDR {idr.sensitivity_ma or 30}mA</text>'
            if idr is not None
            else ""
        )
        svg_circuits_markup.append(
            f"""
            <g class="circuit" data-circuit-id="{escape(circ.circuit_id)}">
              <line x1="{svg_x}" y1="150" x2="{svg_x}" y2="185" stroke="#2563eb" stroke-width="2"/>
              <rect x="{svg_x - 14}" y="185" width="28" height="32" fill="#eff6ff" stroke="#1d4ed8" stroke-width="2"/>
              <line x1="{svg_x}" y1="217" x2="{svg_x}" y2="290" stroke="#2563eb" stroke-width="2"/>
              {svg_idr}
              <text x="{svg_x}" y="308" text-anchor="middle" font-size="12" font-weight="bold" fill="#0f172a">{escape(circ.circuit_id)}</text>
              <text x="{svg_x}" y="324" text-anchor="middle" font-size="10" fill="#334155">{escape(_format_breaker_label(breaker))}</text>
              <text x="{svg_x}" y="338" text-anchor="middle" font-size="10" fill="#475569">{circ.cable_phase_mm2:.1f}mm² • {circ.load_power_va:.0f}VA</text>
              <text x="{svg_x}" y="352" text-anchor="middle" font-size="9" fill="#64748b">{escape(circ.name[:20])}</text>
            </g>
            """
        )

    # 5. CREA/ART + SHA-256 Title Block (Carimbo)
    msp.add_lwpolyline(
        [(10, 10), (total_width, 10), (total_width, 36), (10, 36), (10, 10)],
        dxfattribs={"layer": "EV_CARIMBO"},
    )
    msp.add_text(
        f"ELECTROVISION AI - DIAGRAMA UNIFILAR | QUADRO: {panel.name} ({panel.panel_id})",
        height=2.8,
        dxfattribs={"layer": "EV_CARIMBO", "insert": (15, 29)},
    )
    msp.add_text(
        f"ENG. RESPONSAVEL: {engineer_name} | CREA: {engineer_crea} | ART: {art_number or 'N/A'}",
        height=2.5,
        dxfattribs={"layer": "EV_CARIMBO", "insert": (15, 22)},
    )
    msp.add_text(
        f"DIGITAL TWIN SHA-256: {twin_hash}",
        height=2.1,
        dxfattribs={"layer": "EV_CARIMBO", "insert": (15, 14)},
    )

    # Save audited DXF atomically
    saved_dxf, audit_res = save_audited_dxf_atomically(doc, dxf_destination, base_dir=base_dir)

    # Build matching SVG
    svg_width = max(680, 120 + n_circuits * 140)
    svg_height = 440
    svg_feeder_x = svg_width // 2
    svg_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_width} {svg_height}" width="{svg_width}" height="{svg_height}" font-family="Inter, Arial, sans-serif">
  <rect x="0" y="0" width="{svg_width}" height="{svg_height}" fill="#ffffff"/>
  <rect x="12" y="12" width="{svg_width - 24}" height="{svg_height - 24}" fill="none" stroke="#0f172a" stroke-width="2"/>
  <text x="24" y="34" font-size="13" font-weight="bold" fill="#0f172a">DIAGRAMA UNIFILAR — {escape(panel.name)} ({escape(panel.supply_system.value)})</text>
  <line x1="{svg_feeder_x}" y1="45" x2="{svg_feeder_x}" y2="75" stroke="#dc2626" stroke-width="3"/>
  <rect x="{svg_feeder_x - 22}" y="75" width="44" height="34" fill="#fef2f2" stroke="#dc2626" stroke-width="2"/>
  <text x="{svg_feeder_x + 30}" y="96" font-size="11" fill="#991b1b">DJ Geral: {escape(_format_breaker_label(main_breaker))}</text>
  <line x1="{svg_feeder_x}" y1="109" x2="{svg_feeder_x}" y2="150" stroke="#dc2626" stroke-width="3"/>
  <line x1="30" y1="150" x2="{svg_width - 30}" y2="150" stroke="#dc2626" stroke-width="4"/>
  {''.join(svg_circuits_markup)}
  <rect x="12" y="{svg_height - 62}" width="{svg_width - 24}" height="50" fill="#f8fafc" stroke="#0f172a" stroke-width="1"/>
  <text x="24" y="{svg_height - 42}" font-size="11" fill="#0f172a">Eng. Responsável: {escape(engineer_name)} | CREA: {escape(engineer_crea)} | ART: {escape(art_number or 'N/A')}</text>
  <text x="24" y="{svg_height - 22}" font-size="9" fill="#475569">DigitalTwin SHA-256: {twin_hash}</text>
</svg>
"""
    saved_svg = atomic_write_text(svg_destination, svg_content, base_dir=base_dir)

    return UnifilarExportResult(
        dxf_path=saved_dxf,
        svg_path=saved_svg,
        dxf_audit=audit_res,
    )
