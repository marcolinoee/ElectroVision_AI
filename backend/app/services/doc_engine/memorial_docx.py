"""Technical Memorial & Electrical Compliance Report (.DOCX) generator via python-docx."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

from docx import Document
from docx.shared import Pt

from app.core.storage import atomic_write_bytes
from app.schemas.digital_twin import DigitalTwinJSON
from app.services.compliance.deterministic_engine import ComplianceReport


def generate_memorial_docx(
    digital_twin: DigitalTwinJSON,
    compliance_report: ComplianceReport,
    destination: Path,
    engineer_name: str,
    engineer_crea: str,
    art_number: str | None = None,
    project_name: str = "Projeto Elétrico",
    client_name: str = "Cliente",
    base_dir: Path | None = None,
) -> Path:
    """Generate an audited Memorial Descritivo & Laudo Técnico (.DOCX) atomically."""
    doc = Document()

    style_normal = doc.styles["Normal"]
    style_normal.font.name = "Calibri"
    style_normal.font.size = Pt(10.5)

    # 1. Cover & Identification
    doc.add_heading("MEMORIAL DESCRITIVO E LAUDO DE CONFORMIDADE ELÉTRICA", level=0)
    doc.add_paragraph(f"Projeto: {project_name}")
    doc.add_paragraph(f"Cliente: {client_name}")
    doc.add_paragraph(f"Quadro Inspecionado: {digital_twin.panel.name} ({digital_twin.panel.panel_id})")
    doc.add_paragraph(
        f"Sistema: {digital_twin.panel.supply_system.value} | "
        f"Tensão Nominal: {digital_twin.panel.nominal_voltage_v:.0f} V | "
        f"Aterramento: {digital_twin.panel.grounding_scheme.value}"
    )

    doc.add_heading("1. Responsabilidade Técnica e Integridade Criptográfica", level=1)
    doc.add_paragraph(f"Engenheiro Responsável: {engineer_name}")
    doc.add_paragraph(f"Registro CREA: {engineer_crea}")
    doc.add_paragraph(f"ART: {art_number or 'Não informada'}")
    doc.add_paragraph(f"Data/Hora UTC de Emissão: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    doc.add_paragraph(f"SHA-256 do DigitalTwinJSON Validado: {compliance_report.digital_twin_sha256}")

    # 2. Compliance Summary
    doc.add_heading("2. Resumo Executivo de Conformidade (NBR 5410 / NR-10 / NBR 14039)", level=1)
    status_label = "CONFORME" if compliance_report.is_compliant else "NÃO CONFORME (REQUER ADEQUAÇÃO)"
    doc.add_paragraph(f"Status Determinístico: {status_label}")
    doc.add_paragraph(
        f"Índice de Conformidade: {compliance_report.compliance_score_pct:.1f}% | "
        f"Críticas: {compliance_report.critical_count} | "
        f"Altas: {compliance_report.high_count} | "
        f"Médias: {compliance_report.medium_count} | "
        f"Baixas: {compliance_report.low_count}"
    )

    # 3. Circuit Calculations Table
    doc.add_heading("3. Quadro de Cargas e Verificações Determinísticas", level=1)
    if compliance_report.circuit_calculations:
        tbl = doc.add_table(rows=1, cols=7)
        tbl.style = "Table Grid"
        headers = ["Circuito", "Descrição", "Ib (A)", "In (A)", "Iz (A)", "Queda ΔV (%)", "Status"]
        for i, header in enumerate(headers):
            tbl.rows[0].cells[i].text = header

        for calc in compliance_report.circuit_calculations:
            row = tbl.add_row().cells
            row[0].text = calc.circuit_id
            row[1].text = calc.circuit_name
            row[2].text = f"{calc.design_current_ib_a:.2f}"
            row[3].text = f"{calc.breaker_rated_in_a:.1f}" if calc.breaker_rated_in_a else "N/I"
            row[4].text = f"{calc.corrected_ampacity_iz_a:.2f}"
            row[5].text = f"{calc.voltage_drop_pct:.2f}%"
            row[6].text = "OK" if (calc.coordination_ok and calc.voltage_drop_ok) else "PENDÊNCIA"
    else:
        doc.add_paragraph("Nenhum circuito terminal cadastrado no DigitalTwinJSON.")

    # 4. Findings Table
    doc.add_heading("4. Relatório de Não-Conformidades e Plano de Ação", level=1)
    if compliance_report.findings:
        ftbl = doc.add_table(rows=1, cols=5)
        ftbl.style = "Table Grid"
        for i, h in enumerate(["Norma / Item", "Severidade", "Alvo", "Descrição", "Ação Recomendada"]):
            ftbl.rows[0].cells[i].text = h
        for f in compliance_report.findings:
            r = ftbl.add_row().cells
            r[0].text = f"{f.standard_code} ({f.section_ref})"
            r[1].text = f.severity.value
            r[2].text = f.target_id
            r[3].text = f.description
            r[4].text = f.recommended_action
    else:
        doc.add_paragraph("Nenhuma não-conformidade identificada pelo motor determinístico.")

    buf = io.BytesIO()
    doc.save(buf)
    return atomic_write_bytes(destination, buf.getvalue(), base_dir=base_dir)
