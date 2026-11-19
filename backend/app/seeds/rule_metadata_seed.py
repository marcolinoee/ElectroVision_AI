"""Structured normative rule metadata seeder (NBR 5410 / NR-10 / NBR 14039).

COPYRIGHT GUARDRAIL:
This module contains ONLY structured engineering calculation parameters, thresholds,
and original technical summaries. It does NOT contain full or verbatim copyrighted
ABNT normative text. Users may import their own legally acquired PDFs locally into
`./storage/norms_pdfs` for pgvector citation indexing.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SeverityLevel
from app.models.rule_metadata import RuleMetadata

RULE_METADATA_SEED: list[dict[str, Any]] = [
    {
        "rule_code": "NBR5410_IDR_30MA_WET_AREAS",
        "standard_code": "NBR 5410",
        "section_ref": "5.1.3.2.2",
        "title": "Proteção diferencial-residual (IDR <= 30 mA) em áreas molhadas e externas",
        "category": "PROTECAO_CHOQUE",
        "severity": SeverityLevel.CRITICA,
        "parameters_json": {
            "max_sensitivity_ma": 30,
            "applies_to_wet_areas": True,
            "applies_to_external_areas": True,
        },
        "check_summary": "Circuitos que atendem áreas molhadas ou externas devem dispor de proteção IDR de alta sensibilidade (<= 30 mA).",
        "recommended_action": "Instalar interruptor diferencial-residual (IDR) com sensibilidade nominal de 30 mA compatível com a corrente nominal do circuito ou grupo.",
    },
    {
        "rule_code": "NBR5410_DPS_SURGE_PROTECTION",
        "standard_code": "NBR 5410",
        "section_ref": "5.4.2",
        "title": "Presença de Dispositivo de Proteção contra Surtos (DPS)",
        "category": "PROTECAO_SOBRETENSAO",
        "severity": SeverityLevel.ALTA,
        "parameters_json": {
            "required_on_panel": True,
            "recommended_classes": ["I", "II", "I+II"],
            "min_imax_ka": 20.0,
        },
        "check_summary": "Quadros alimentados por linha externa aérea ou sujeitos a sobretensões transitórias devem possuir DPS coordenado com o aterramento.",
        "recommended_action": "Instalar conjunto de DPS Classe II (ou I+II) entre fases/neutro e barramento de equipotencialização (PE), observando Uc >= tensão fase-terra.",
    },
    {
        "rule_code": "NBR5410_MIN_SECTION_LIGHTING",
        "standard_code": "NBR 5410",
        "section_ref": "6.2.6.1.1",
        "title": "Seção mínima de condutores de cobre para circuitos de iluminação",
        "category": "DIMENSIONAMENTO_CONDUTORES",
        "severity": SeverityLevel.ALTA,
        "parameters_json": {
            "circuit_kind": "ILUMINACAO",
            "min_copper_section_mm2": 1.5,
        },
        "check_summary": "Circuitos terminais de iluminação em cobre devem utilizar seção nominal mínima de 1,5 mm².",
        "recommended_action": "Substituir condutores com seção inferior a 1,5 mm² por cabo de cobre isolado de no mínimo 1,5 mm².",
    },
    {
        "rule_code": "NBR5410_MIN_SECTION_POWER",
        "standard_code": "NBR 5410",
        "section_ref": "6.2.6.1.1",
        "title": "Seção mínima de condutores de cobre para circuitos de força e tomadas",
        "category": "DIMENSIONAMENTO_CONDUTORES",
        "severity": SeverityLevel.ALTA,
        "parameters_json": {
            "circuit_kinds": ["TOMADAS_USO_GERAL", "TUE", "MOTOR"],
            "min_copper_section_mm2": 2.5,
        },
        "check_summary": "Circuitos terminais de força e tomadas em cobre devem utilizar seção nominal mínima de 2,5 mm².",
        "recommended_action": "Substituir condutores subdimensionados por cabo de cobre isolado de no mínimo 2,5 mm² (ou maior conforme ampacidade/queda de tensão).",
    },
    {
        "rule_code": "NBR5410_BREAKER_CABLE_COORDINATION",
        "standard_code": "NBR 5410",
        "section_ref": "5.3.4.1",
        "title": "Coordenação entre corrente de projeto (Ib), disjuntor (In) e ampacidade do cabo (Iz)",
        "category": "PROTECAO_SOBRECARGA",
        "severity": SeverityLevel.CRITICA,
        "parameters_json": {
            "condition": "Ib <= In <= Iz",
            "ampacity_pvc_b1_2_loaded_a": {
                "1.5": 17.5,
                "2.5": 24.0,
                "4.0": 32.0,
                "6.0": 41.0,
                "10.0": 57.0,
                "16.0": 76.0,
                "25.0": 101.0,
                "35.0": 125.0,
            },
        },
        "check_summary": "A corrente nominal do dispositivo de proteção (In) deve ser maior ou igual à corrente de projeto (Ib) e menor ou igual à capacidade de condução corrigida do condutor (Iz).",
        "recommended_action": "Redimensionar o disjuntor ou elevar a seção do condutor para restabelecer a desigualdade Ib <= In <= Iz.",
    },
    {
        "rule_code": "NBR5410_VOLTAGE_DROP_LIMIT",
        "standard_code": "NBR 5410",
        "section_ref": "6.2.7",
        "title": "Limite de queda de tensão em circuitos terminais",
        "category": "QUEDA_TENSAO",
        "severity": SeverityLevel.MEDIA,
        "parameters_json": {
            "max_terminal_drop_pct": 4.0,
            "max_total_drop_utility_pct": 5.0,
            "max_total_drop_substation_pct": 7.0,
            "copper_resistivity_ohm_mm2_m": 0.0172,
        },
        "check_summary": "A queda de tensão calculada no circuito terminal não deve exceder 4% em regime permanente.",
        "recommended_action": "Aumentar a seção do condutor ou reduzir o comprimento do trecho para manter a queda de tensão abaixo de 4%.",
    },
    {
        "rule_code": "NBR5410_CONDUCTOR_COLOR_NEUTRAL_PE",
        "standard_code": "NBR 5410",
        "section_ref": "6.1.5.3",
        "title": "Identificação cromática obrigatória de Neutro (azul-claro) e Proteção PE (verde ou verde-amarelo)",
        "category": "IDENTIFICACAO_CONDUTORES",
        "severity": SeverityLevel.ALTA,
        "parameters_json": {
            "neutral_allowed_colors": ["AZUL_CLARO"],
            "pe_allowed_colors": ["VERDE", "VERDE_AMARELO"],
            "phase_forbidden_colors": ["AZUL_CLARO", "VERDE", "VERDE_AMARELO"],
        },
        "check_summary": "Condutores neutros devem ser identificados em azul-claro e condutores de proteção (PE) em verde ou verde-amarelo; fases não podem usar essas cores.",
        "recommended_action": "Adequar a identificação ou substituir os condutores fora do padrão cromático para eliminar risco de inversão em manutenção.",
    },
    {
        "rule_code": "NBR5410_SEPARATE_NEUTRAL_PE_BUSBARS",
        "standard_code": "NBR 5410",
        "section_ref": "5.1.2.2",
        "title": "Separação entre barramento de Neutro (N) e barramento de Proteção (PE) em esquema TN-S/TT",
        "category": "ATERRAMENTO",
        "severity": SeverityLevel.CRITICA,
        "parameters_json": {
            "requires_separate_busbars_for": ["TN_S", "TT", "TN_C_S"],
        },
        "check_summary": "Nos esquemas TN-S, TT e a jusante do ponto de separação TN-C-S, os barramentos de Neutro e Terra (PE) devem ser fisicamente independentes.",
        "recommended_action": "Instalar barramentos dedicados e isolados para Neutro e para Terra (PE), eliminando interligações indevidas a jusante do IDR.",
    },
    {
        "rule_code": "NR10_WARNING_SIGN_AND_UNIFILAR",
        "standard_code": "NR-10",
        "section_ref": "10.2.3 / 10.10.1",
        "title": "Sinalização de risco elétrico e diagrama unifilar atualizado no interior do quadro",
        "category": "SEGURANCA_OPERACIONAL",
        "severity": SeverityLevel.MEDIA,
        "parameters_json": {
            "requires_warning_sign": True,
            "requires_unifilar_inside": True,
        },
        "check_summary": "Quadros elétricos devem apresentar sinalização de advertência de risco de choque elétrico e prontuário/diagrama unifilar atualizado.",
        "recommended_action": "Fixar placa de sinalização NR-10 na porta do quadro e disponibilizar o diagrama unifilar validado em porta-documentos interno.",
    },
    {
        "rule_code": "NBR14039_MV_PROTECTION_METADATA",
        "standard_code": "NBR 14039",
        "section_ref": "5.3",
        "title": "Requisitos de proteção e seccionamento para instalações em Média Tensão (> 1 kV)",
        "category": "MEDIA_TENSAO",
        "severity": SeverityLevel.CRITICA,
        "parameters_json": {
            "voltage_threshold_v": 1000.0,
            "requires_dedicated_mv_protection": True,
            "requires_door_grounding": True,
        },
        "check_summary": "Instalações acima de 1 kV requerem verificação dedicada de cubículo, aterramento de partes metálicas e coordenação de proteção de média tensão.",
        "recommended_action": "Acionar estudo de seletividade e coordenação de média tensão e garantir aterramento efetivo da carcaça/porta do cubículo.",
    },
]


async def seed_rule_metadata(session: AsyncSession) -> int:
    """Idempotently insert or update structured normative rule metadata."""
    inserted = 0
    for item in RULE_METADATA_SEED:
        existing = await session.scalar(
            select(RuleMetadata).where(RuleMetadata.rule_code == item["rule_code"])
        )
        if existing is None:
            session.add(RuleMetadata(**item))
            inserted += 1
        else:
            for field, value in item.items():
                setattr(existing, field, value)
    await session.flush()
    return inserted
