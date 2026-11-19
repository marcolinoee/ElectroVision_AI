"""Load Schedule & SINAPI Retrofit Budget (.XLSX) generator via openpyxl."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from app.core.storage import atomic_write_bytes
from app.schemas.digital_twin import DigitalTwinJSON
from app.seeds.sinapi_eletrica_seed import SINAPI_ELETRICA_SEED
from app.services.compliance.deterministic_engine import ComplianceReport


def generate_retrofit_xlsx(
    digital_twin: DigitalTwinJSON,
    compliance_report: ComplianceReport,
    destination: Path,
    engineer_name: str,
    engineer_crea: str,
    art_number: str | None = None,
    sinapi_catalog: list[dict[str, Any]] | None = None,
    base_dir: Path | None = None,
) -> Path:
    """Generate a 3-sheet formatted .XLSX workbook (Load Schedule, Findings, SINAPI Budget) atomically."""
    catalog = sinapi_catalog if sinapi_catalog is not None else SINAPI_ELETRICA_SEED
    sinapi_by_category: dict[str, dict[str, Any]] = {
        str(item["category"]): item for item in catalog
    }

    wb = Workbook()
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)

    # Sheet 1: Quadro de Cargas
    ws_loads = wb.active
    assert ws_loads is not None
    ws_loads.title = "Quadro_de_Cargas"
    ws_loads.append(["ELECTROVISION AI — QUADRO DE CARGAS E DIMENSIONAMENTO NBR 5410"])
    ws_loads.append(
        [
            f"Quadro: {digital_twin.panel.name}",
            f"Eng.: {engineer_name}",
            f"CREA: {engineer_crea}",
            f"ART: {art_number or 'N/A'}",
        ]
    )
    ws_loads.append(["DigitalTwin SHA-256:", compliance_report.digital_twin_sha256])
    ws_loads.append([])

    load_headers = ["Circuito", "Nome", "Ib (A)", "In (A)", "Iz (A)", "FCT", "FCA", "ΔV (%)", "Coord. OK", "ΔV OK"]
    ws_loads.append(load_headers)
    for cell in ws_loads[5]:
        cell.fill = header_fill
        cell.font = header_font

    for calc in compliance_report.circuit_calculations:
        ws_loads.append(
            [
                calc.circuit_id,
                calc.circuit_name,
                calc.design_current_ib_a,
                calc.breaker_rated_in_a,
                calc.corrected_ampacity_iz_a,
                calc.fct,
                calc.fca,
                calc.voltage_drop_pct,
                "SIM" if calc.coordination_ok else "NÃO",
                "SIM" if calc.voltage_drop_ok else "NÃO",
            ]
        )

    # Sheet 2: Não-Conformidades
    ws_nc = wb.create_sheet("Nao_Conformidades")
    nc_headers = ["Regra", "Norma", "Item", "Severidade", "Alvo", "Descrição", "Ação Recomendada"]
    ws_nc.append(nc_headers)
    for cell in ws_nc[1]:
        cell.fill = header_fill
        cell.font = header_font

    for finding in compliance_report.findings:
        ws_nc.append(
            [
                finding.rule_code,
                finding.standard_code,
                finding.section_ref,
                finding.severity.value,
                finding.target_id,
                finding.description,
                finding.recommended_action,
            ]
        )

    # Sheet 3: Orçamento de Retrofit SINAPI
    ws_budget = wb.create_sheet("Orcamento_Retrofit_SINAPI")
    budget_headers = ["Código SINAPI", "Descrição", "Unid.", "Quantidade", "Preço Unit. (R$)", "Subtotal (R$)"]
    ws_budget.append(budget_headers)
    for cell in ws_budget[1]:
        cell.fill = header_fill
        cell.font = header_font

    # Aggregate suggested SINAPI quantities across all findings
    qty_by_category: dict[str, float] = {}
    for finding in compliance_report.findings:
        if finding.suggested_sinapi_category:
            cat = finding.suggested_sinapi_category
            qty_by_category[cat] = qty_by_category.get(cat, 0.0) + finding.suggested_quantity

    # Always include base electrician labor hours when findings exist
    if compliance_report.findings and "MAO_DE_OBRA_ELETRICISTA" not in qty_by_category:
        qty_by_category["MAO_DE_OBRA_ELETRICISTA"] = float(max(2, len(compliance_report.findings) * 2))

    row_idx = 2
    for cat, qty in sorted(qty_by_category.items()):
        item = sinapi_by_category.get(cat)
        if item is None:
            continue
        ws_budget.append(
            [
                item["sinapi_code"],
                item["description"],
                item["unit"],
                round(qty, 2),
                float(item["unit_price_brl"]),
                f"=D{row_idx}*E{row_idx}",
            ]
        )
        row_idx += 1

    if row_idx > 2:
        ws_budget.append(["", "TOTAL ESTIMADO RETROFIT (R$)", "", "", "", f"=SUM(F2:F{row_idx - 1})"])
        ws_budget[f"B{row_idx}"].font = Font(bold=True)
        ws_budget[f"F{row_idx}"].font = Font(bold=True)

    buf = io.BytesIO()
    wb.save(buf)
    return atomic_write_bytes(destination, buf.getvalue(), base_dir=base_dir)
