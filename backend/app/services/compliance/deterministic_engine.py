"""Deterministic Electrical Compliance Engine (NBR 5410 / NR-10 / NBR 14039).

ARCHITECTURE GUARDRAIL:
This engine evaluates EXCLUSIVELY the structured `DigitalTwinJSON` using deterministic
engineering formulas and normative thresholds. RAG/pgvector NEVER alters compliance verdicts.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import CableColor, ComponentType, GroundingScheme, SeverityLevel
from app.schemas.digital_twin import CircuitSpec, DigitalTwinJSON, PanelComponent

# Copper resistivity at 70°C (PVC) / 90°C (XLPE/EPR) in ohm·mm²/m
_COPPER_RESISTIVITY_PVC_70C: float = 0.0217  # ~1.26 * 0.01724 at operating temp 70°C
_MAX_TERMINAL_VOLTAGE_DROP_PCT: float = 4.0

# Reference current-carrying capacity Iz0 (A) for copper PVC 70°C, 2 loaded conductors, 30°C
# Structured engineering lookup table (NBR 5410 methods A1, A2, B1, B2, C, D)
_AMPACITY_TABLE_PVC_2C: dict[str, dict[float, float]] = {
    "A1": {1.5: 14.5, 2.5: 19.5, 4.0: 26.0, 6.0: 34.0, 10.0: 46.0, 16.0: 61.0, 25.0: 80.0, 35.0: 99.0},
    "A2": {1.5: 14.0, 2.5: 18.5, 4.0: 25.0, 6.0: 32.0, 10.0: 43.0, 16.0: 57.0, 25.0: 75.0, 35.0: 92.0},
    "B1": {1.5: 17.5, 2.5: 24.0, 4.0: 32.0, 6.0: 41.0, 10.0: 57.0, 16.0: 76.0, 25.0: 101.0, 35.0: 125.0},
    "B2": {1.5: 16.5, 2.5: 23.0, 4.0: 30.0, 6.0: 38.0, 10.0: 52.0, 16.0: 69.0, 25.0: 90.0, 35.0: 111.0},
    "C": {1.5: 19.5, 2.5: 27.0, 4.0: 36.0, 6.0: 46.0, 10.0: 63.0, 16.0: 85.0, 25.0: 112.0, 35.0: 138.0},
    "D": {1.5: 22.0, 2.5: 29.0, 4.0: 38.0, 6.0: 47.0, 10.0: 63.0, 16.0: 81.0, 25.0: 104.0, 35.0: 125.0},
}

# Temperature correction factor FCT for PVC 70°C (reference 30°C)
_TEMP_CORRECTION_PVC: list[tuple[float, float]] = [
    (25.0, 1.06),
    (30.0, 1.00),
    (35.0, 0.94),
    (40.0, 0.87),
    (45.0, 0.79),
    (50.0, 0.71),
    (55.0, 0.61),
    (60.0, 0.50),
]

# Grouping correction factor FCA (number of bunched circuits)
_GROUPING_CORRECTION: dict[int, float] = {
    1: 1.00,
    2: 0.80,
    3: 0.70,
    4: 0.65,
    5: 0.60,
    6: 0.57,
    7: 0.54,
    8: 0.52,
    9: 0.50,
}

_THREE_PHASE_ALLOCATIONS = {"F1-F2-F3"}


class CircuitCalculation(BaseModel):
    """Deterministic electrical calculation per circuit."""

    model_config = ConfigDict(extra="forbid")

    circuit_id: str
    circuit_name: str
    design_current_ib_a: float
    breaker_rated_in_a: float | None
    corrected_ampacity_iz_a: float
    fct: float
    fca: float
    voltage_drop_pct: float
    coordination_ok: bool
    voltage_drop_ok: bool


class ComplianceFinding(BaseModel):
    """Single deterministic non-conformity finding."""

    model_config = ConfigDict(extra="forbid")

    rule_code: str
    standard_code: str
    section_ref: str
    severity: SeverityLevel
    target_id: str
    title: str
    description: str
    recommended_action: str
    suggested_sinapi_category: str | None = None
    suggested_quantity: float = 1.0
    measured_values: dict[str, Any] = Field(default_factory=dict)


class ComplianceReport(BaseModel):
    """Complete deterministic compliance report for a DigitalTwinJSON."""

    model_config = ConfigDict(extra="forbid")

    panel_id: str
    digital_twin_sha256: str
    is_compliant: bool
    compliance_score_pct: float
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    circuit_calculations: list[CircuitCalculation]
    findings: list[ComplianceFinding]


def _lookup_fct(ambient_temp_c: float) -> float:
    for temp_limit, factor in _TEMP_CORRECTION_PVC:
        if ambient_temp_c <= temp_limit:
            return factor
    return 0.50


def _lookup_fca(grouping_count: int) -> float:
    if grouping_count <= 1:
        return 1.00
    if grouping_count >= 9:
        return 0.50
    return _GROUPING_CORRECTION[grouping_count]


def _lookup_base_ampacity(method: str, section_mm2: float, is_three_phase: bool) -> float:
    table = _AMPACITY_TABLE_PVC_2C.get(method, _AMPACITY_TABLE_PVC_2C["B1"])
    sections = sorted(table.keys())
    base_val = table[sections[0]]
    for sec in sections:
        if section_mm2 >= sec:
            base_val = table[sec]
        else:
            break
    # Three loaded conductors reduce ampacity by ~0.88 relative to 2 loaded conductors
    return base_val * (0.88 if is_three_phase else 1.0)


def calculate_circuit_metrics(
    circuit: CircuitSpec,
    breaker: PanelComponent | None,
) -> CircuitCalculation:
    """Compute Ib, Iz (corrected), and DeltaV% deterministically per NBR 5410."""
    is_3ph = circuit.phase_allocation in _THREE_PHASE_ALLOCATIONS
    if is_3ph:
        ib = circuit.load_power_va / (math.sqrt(3.0) * circuit.voltage_v)
    else:
        ib = circuit.load_power_va / circuit.voltage_v

    fct = _lookup_fct(circuit.ambient_temp_c)
    fca = _lookup_fca(circuit.grouping_count)
    iz0 = _lookup_base_ampacity(circuit.installation_method, circuit.cable_phase_mm2, is_3ph)
    iz = iz0 * fct * fca

    factor_phase = math.sqrt(3.0) if is_3ph else 2.0
    delta_v = (
        factor_phase
        * _COPPER_RESISTIVITY_PVC_70C
        * circuit.length_m
        * ib
        * circuit.power_factor
        / circuit.cable_phase_mm2
    )
    delta_v_pct = (delta_v / circuit.voltage_v) * 100.0

    breaker_in = breaker.rated_current_a if breaker is not None else None
    coordination_ok = breaker_in is not None and (ib <= breaker_in <= iz)
    voltage_drop_ok = delta_v_pct <= _MAX_TERMINAL_VOLTAGE_DROP_PCT

    return CircuitCalculation(
        circuit_id=circuit.circuit_id,
        circuit_name=circuit.name,
        design_current_ib_a=round(ib, 2),
        breaker_rated_in_a=breaker_in,
        corrected_ampacity_iz_a=round(iz, 2),
        fct=fct,
        fca=fca,
        voltage_drop_pct=round(delta_v_pct, 2),
        coordination_ok=coordination_ok,
        voltage_drop_ok=voltage_drop_ok,
    )


def evaluate_digital_twin_compliance(digital_twin: DigitalTwinJSON) -> ComplianceReport:
    """Run all deterministic NBR 5410, NR-10, and NBR 14039 checks on DigitalTwinJSON."""
    findings: list[ComplianceFinding] = []
    calculations: list[CircuitCalculation] = []

    comp_map: dict[str, PanelComponent] = {c.component_id: c for c in digital_twin.components}
    panel = digital_twin.panel

    # 1. DPS Presence Check (NBR 5410 5.4.2)
    dps_components = [c for c in digital_twin.components if c.component_type == ComponentType.DPS]
    if not panel.has_dps and not dps_components:
        findings.append(
            ComplianceFinding(
                rule_code="NBR5410_DPS_SURGE_PROTECTION",
                standard_code="NBR 5410",
                section_ref="5.4.2",
                severity=SeverityLevel.ALTA,
                target_id=panel.panel_id,
                title="Ausência de Dispositivo de Proteção contra Surtos (DPS)",
                description=f"O quadro '{panel.name}' não possui DPS instalado para proteção contra sobretensões transitórias.",
                recommended_action="Instalar conjunto de DPS Classe II (275V, >= 20kA) conectado ao barramento PE.",
                suggested_sinapi_category="DPS_CLASSE_II",
                suggested_quantity=3.0 if "TRIFASICO" in panel.supply_system.value else 2.0,
            )
        )

    # 2. Separate Neutral & PE Busbars (NBR 5410 5.1.2.2)
    if (
        panel.grounding_scheme in {GroundingScheme.TN_S, GroundingScheme.TT, GroundingScheme.TN_C_S}
        and (not panel.has_pe_busbar or not panel.has_neutral_busbar or not panel.pe_neutral_separated)
    ):
        findings.append(
            ComplianceFinding(
                rule_code="NBR5410_SEPARATE_NEUTRAL_PE_BUSBARS",
                standard_code="NBR 5410",
                section_ref="5.1.2.2",
                severity=SeverityLevel.CRITICA,
                target_id=panel.panel_id,
                title="Barramentos de Neutro (N) e Proteção (PE) ausentes ou não separados",
                description=(
                    f"No esquema {panel.grounding_scheme.value}, o quadro '{panel.name}' "
                    "deve possuir barramentos independentes para Neutro e Terra (PE)."
                ),
                recommended_action="Instalar barramentos isolados e independentes para Neutro e PE.",
                suggested_sinapi_category="BARRAMENTO_N_PE",
                suggested_quantity=2.0,
            )
        )

    # 3. NR-10 Warning Sign & Unifilar Diagram Inside Panel
    if not panel.warning_sign_nr10_present or not panel.unifilar_diagram_inside_present:
        missing_parts: list[str] = []
        if not panel.warning_sign_nr10_present:
            missing_parts.append("placa de sinalização de risco elétrico")
        if not panel.unifilar_diagram_inside_present:
            missing_parts.append("diagrama unifilar atualizado no interior da porta")
        findings.append(
            ComplianceFinding(
                rule_code="NR10_WARNING_SIGN_AND_UNIFILAR",
                standard_code="NR-10",
                section_ref="10.2.3 / 10.10.1",
                severity=SeverityLevel.MEDIA,
                target_id=panel.panel_id,
                title="Pendência documental e de sinalização NR-10 no quadro",
                description=f"Falta no quadro '{panel.name}': {', '.join(missing_parts)}.",
                recommended_action="Fixar sinalização NR-10 na porta e inserir o diagrama unifilar validado.",
                suggested_sinapi_category="SINALIZACAO_NR10",
                suggested_quantity=1.0,
            )
        )

    # 4. NBR 14039 Medium Voltage (> 1000 V) Check
    if panel.nominal_voltage_v > 1000.0 and not panel.door_grounding_present:
        findings.append(
            ComplianceFinding(
                rule_code="NBR14039_MV_PROTECTION_METADATA",
                standard_code="NBR 14039",
                section_ref="5.3",
                severity=SeverityLevel.CRITICA,
                target_id=panel.panel_id,
                title="Ausência de aterramento da porta/carcaça em instalação de Média Tensão",
                description=(
                    f"Instalação com tensão nominal {panel.nominal_voltage_v:.0f} V (> 1 kV) "
                    "sem aterramento confirmado da porta metálica."
                ),
                recommended_action="Executar cordoalha de aterramento da porta e validar proteção de Média Tensão.",
                suggested_sinapi_category="MAO_DE_OBRA_ELETRICISTA",
                suggested_quantity=4.0,
            )
        )

    # 5. Component-level Cable Color Check (vision-detected loose cables)
    for comp in digital_twin.components:
        if comp.cable_spec is None:
            continue
        role = comp.cable_spec.conductor_role
        color = comp.cable_spec.color
        if color == CableColor.DESCONHECIDA:
            continue
        if role == "NEUTRO" and color != CableColor.AZUL_CLARO:
            findings.append(
                ComplianceFinding(
                    rule_code="NBR5410_CONDUCTOR_COLOR_NEUTRAL_PE",
                    standard_code="NBR 5410",
                    section_ref="6.1.5.3",
                    severity=SeverityLevel.ALTA,
                    target_id=comp.component_id,
                    title="Condutor Neutro fora do padrão cromático (azul-claro)",
                    description=f"Componente '{comp.label}' (Neutro) identificado na cor {color.value}.",
                    recommended_action="Substituir ou identificar o condutor neutro exclusivamente em azul-claro.",
                    suggested_sinapi_category="CABO_2_5MM",
                    suggested_quantity=10.0,
                )
            )
        elif role == "TERRA_PE" and color not in {CableColor.VERDE, CableColor.VERDE_AMARELO}:
            findings.append(
                ComplianceFinding(
                    rule_code="NBR5410_CONDUCTOR_COLOR_NEUTRAL_PE",
                    standard_code="NBR 5410",
                    section_ref="6.1.5.3",
                    severity=SeverityLevel.ALTA,
                    target_id=comp.component_id,
                    title="Condutor de Proteção (PE) fora do padrão cromático (verde/verde-amarelo)",
                    description=f"Componente '{comp.label}' (PE) identificado na cor {color.value}.",
                    recommended_action="Substituir o condutor PE por cabo verde ou verde-amarelo.",
                    suggested_sinapi_category="CABO_2_5MM",
                    suggested_quantity=10.0,
                )
            )
        elif role == "FASE" and color in {CableColor.AZUL_CLARO, CableColor.VERDE, CableColor.VERDE_AMARELO}:
            findings.append(
                ComplianceFinding(
                    rule_code="NBR5410_CONDUCTOR_COLOR_NEUTRAL_PE",
                    standard_code="NBR 5410",
                    section_ref="6.1.5.3",
                    severity=SeverityLevel.CRITICA,
                    target_id=comp.component_id,
                    title="Condutor Fase utilizando cor exclusiva de Neutro ou Terra (PE)",
                    description=f"Componente '{comp.label}' (Fase) identificado na cor proibida {color.value}.",
                    recommended_action="Substituir imediatamente o condutor fase por cor permitida (preto, vermelho, marrom, branco ou cinza).",
                    suggested_sinapi_category="CABO_2_5MM",
                    suggested_quantity=10.0,
                )
            )

    # 6. Per-Circuit Deterministic Checks
    for circ in digital_twin.circuits:
        breaker = comp_map.get(circ.breaker_component_id) if circ.breaker_component_id else None
        idr = comp_map.get(circ.idr_component_id) if circ.idr_component_id else None

        calc = calculate_circuit_metrics(circ, breaker)
        calculations.append(calc)

        # 6a. Minimum Conductor Section (NBR 5410 6.2.6.1.1)
        if circ.circuit_kind == "ILUMINACAO" and circ.cable_phase_mm2 < 1.5:
            findings.append(
                ComplianceFinding(
                    rule_code="NBR5410_MIN_SECTION_LIGHTING",
                    standard_code="NBR 5410",
                    section_ref="6.2.6.1.1",
                    severity=SeverityLevel.ALTA,
                    target_id=circ.circuit_id,
                    title="Seção mínima de iluminação (< 1,5 mm²) não atendida",
                    description=f"Circuito '{circ.name}' utiliza {circ.cable_phase_mm2} mm² (mínimo: 1,5 mm²).",
                    recommended_action="Substituir cabeamento do circuito por cabo de cobre 1,5 mm².",
                    suggested_sinapi_category="CABO_1_5MM",
                    suggested_quantity=round(circ.length_m * 3.0, 1),
                    measured_values={"cable_phase_mm2": circ.cable_phase_mm2, "min_mm2": 1.5},
                )
            )
        elif circ.circuit_kind in {"TOMADAS_USO_GERAL", "TUE", "MOTOR"} and circ.cable_phase_mm2 < 2.5:
            findings.append(
                ComplianceFinding(
                    rule_code="NBR5410_MIN_SECTION_POWER",
                    standard_code="NBR 5410",
                    section_ref="6.2.6.1.1",
                    severity=SeverityLevel.ALTA,
                    target_id=circ.circuit_id,
                    title="Seção mínima de força/tomadas (< 2,5 mm²) não atendida",
                    description=f"Circuito '{circ.name}' utiliza {circ.cable_phase_mm2} mm² (mínimo: 2,5 mm²).",
                    recommended_action="Substituir cabeamento do circuito por cabo de cobre >= 2,5 mm².",
                    suggested_sinapi_category="CABO_2_5MM",
                    suggested_quantity=round(circ.length_m * 3.0, 1),
                    measured_values={"cable_phase_mm2": circ.cable_phase_mm2, "min_mm2": 2.5},
                )
            )

        # 6b. IDR <= 30 mA for Wet or External Areas (NBR 5410 5.1.3.2.2)
        if circ.is_wet_area or circ.is_external_area:
            idr_valid = (
                idr is not None
                and idr.component_type == ComponentType.IDR
                and idr.sensitivity_ma is not None
                and idr.sensitivity_ma <= 30
            )
            if not idr_valid:
                findings.append(
                    ComplianceFinding(
                        rule_code="NBR5410_IDR_30MA_WET_AREAS",
                        standard_code="NBR 5410",
                        section_ref="5.1.3.2.2",
                        severity=SeverityLevel.CRITICA,
                        target_id=circ.circuit_id,
                        title="Ausência de proteção IDR <= 30 mA em circuito de área molhada/externa",
                        description=f"Circuito '{circ.name}' atende área molhada/externa sem IDR 30 mA válido associado.",
                        recommended_action="Instalar IDR de 30 mA protegendo o circuito ou grupo de circuitos.",
                        suggested_sinapi_category="IDR_BIPOLAR",
                        suggested_quantity=1.0,
                    )
                )

        # 6c. Overload Coordination Ib <= In <= Iz (NBR 5410 5.3.4.1)
        if not calc.coordination_ok:
            findings.append(
                ComplianceFinding(
                    rule_code="NBR5410_BREAKER_CABLE_COORDINATION",
                    standard_code="NBR 5410",
                    section_ref="5.3.4.1",
                    severity=SeverityLevel.CRITICA,
                    target_id=circ.circuit_id,
                    title="Falha na coordenação Ib <= In <= Iz (proteção contra sobrecarga)",
                    description=(
                        f"Circuito '{circ.name}': Ib={calc.design_current_ib_a}A, "
                        f"In={calc.breaker_rated_in_a}A, Iz={calc.corrected_ampacity_iz_a}A."
                    ),
                    recommended_action="Adequar disjuntor (In) ou elevar seção do condutor para atender Ib <= In <= Iz.",
                    suggested_sinapi_category="DISJUNTOR_MONOPOLAR",
                    suggested_quantity=1.0,
                    measured_values={
                        "ib_a": calc.design_current_ib_a,
                        "in_a": calc.breaker_rated_in_a,
                        "iz_a": calc.corrected_ampacity_iz_a,
                    },
                )
            )

        # 6d. Voltage Drop Limit <= 4.0% (NBR 5410 6.2.7)
        if not calc.voltage_drop_ok:
            findings.append(
                ComplianceFinding(
                    rule_code="NBR5410_VOLTAGE_DROP_LIMIT",
                    standard_code="NBR 5410",
                    section_ref="6.2.7",
                    severity=SeverityLevel.MEDIA,
                    target_id=circ.circuit_id,
                    title="Queda de tensão acima do limite normativo (4%)",
                    description=(
                        f"Circuito '{circ.name}' apresenta queda de tensão calculada de "
                        f"{calc.voltage_drop_pct:.2f}% (limite: {_MAX_TERMINAL_VOLTAGE_DROP_PCT:.1f}%)."
                    ),
                    recommended_action="Aumentar a seção do condutor de fase/neutro para reduzir a queda de tensão abaixo de 4%.",
                    suggested_sinapi_category="CABO_4_0MM",
                    suggested_quantity=round(circ.length_m * 2.0, 1),
                    measured_values={
                        "voltage_drop_pct": calc.voltage_drop_pct,
                        "limit_pct": _MAX_TERMINAL_VOLTAGE_DROP_PCT,
                    },
                )
            )

        # 6e. Circuit Conductor Color Check
        if circ.cable_neutral_color and circ.cable_neutral_color not in {
            CableColor.AZUL_CLARO,
            CableColor.DESCONHECIDA,
        }:
            findings.append(
                ComplianceFinding(
                    rule_code="NBR5410_CONDUCTOR_COLOR_NEUTRAL_PE",
                    standard_code="NBR 5410",
                    section_ref="6.1.5.3",
                    severity=SeverityLevel.ALTA,
                    target_id=circ.circuit_id,
                    title="Neutro do circuito fora da cor azul-claro",
                    description=f"Circuito '{circ.name}' usa neutro na cor {circ.cable_neutral_color.value}.",
                    recommended_action="Padronizar condutor neutro em azul-claro.",
                    suggested_sinapi_category="CABO_2_5MM",
                    suggested_quantity=round(circ.length_m, 1),
                )
            )
        if circ.cable_pe_color and circ.cable_pe_color not in {
            CableColor.VERDE,
            CableColor.VERDE_AMARELO,
            CableColor.DESCONHECIDA,
        }:
            findings.append(
                ComplianceFinding(
                    rule_code="NBR5410_CONDUCTOR_COLOR_NEUTRAL_PE",
                    standard_code="NBR 5410",
                    section_ref="6.1.5.3",
                    severity=SeverityLevel.ALTA,
                    target_id=circ.circuit_id,
                    title="Condutor PE do circuito fora da cor verde/verde-amarelo",
                    description=f"Circuito '{circ.name}' usa PE na cor {circ.cable_pe_color.value}.",
                    recommended_action="Padronizar condutor de proteção (PE) em verde ou verde-amarelo.",
                    suggested_sinapi_category="CABO_2_5MM",
                    suggested_quantity=round(circ.length_m, 1),
                )
            )

    critical_count = sum(1 for f in findings if f.severity == SeverityLevel.CRITICA)
    high_count = sum(1 for f in findings if f.severity == SeverityLevel.ALTA)
    medium_count = sum(1 for f in findings if f.severity == SeverityLevel.MEDIA)
    low_count = sum(1 for f in findings if f.severity == SeverityLevel.BAIXA)

    penalty = critical_count * 25 + high_count * 12 + medium_count * 5 + low_count * 2
    score = float(max(0, 100 - penalty))

    return ComplianceReport(
        panel_id=panel.panel_id,
        digital_twin_sha256=digital_twin.canonical_sha256(),
        is_compliant=(critical_count == 0 and high_count == 0),
        compliance_score_pct=score,
        critical_count=critical_count,
        high_count=high_count,
        medium_count=medium_count,
        low_count=low_count,
        circuit_calculations=calculations,
        findings=findings,
    )
