"""SINAPI electrical catalog seeder for deterministic retrofit budgeting (.XLSX)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sinapi_item import SinapiItem

SINAPI_ELETRICA_SEED: list[dict[str, Any]] = [
    {
        "sinapi_code": "93653",
        "description": "Disjuntor monopolar tipo DIN, corrente nominal de 10A a 32A, curva C — fornecimento e instalação",
        "unit": "UN",
        "category": "DISJUNTOR_MONOPOLAR",
        "unit_price_brl": 28.90,
        "reference_month": "2025-01",
        "state_uf": "SP",
        "material_specs_json": {"poles": 1, "curve": "C", "range_a": [10, 32]},
    },
    {
        "sinapi_code": "93660",
        "description": "Disjuntor bipolar tipo DIN, corrente nominal de 16A a 50A, curva C — fornecimento e instalação",
        "unit": "UN",
        "category": "DISJUNTOR_BIPOLAR",
        "unit_price_brl": 64.50,
        "reference_month": "2025-01",
        "state_uf": "SP",
        "material_specs_json": {"poles": 2, "curve": "C", "range_a": [16, 50]},
    },
    {
        "sinapi_code": "93668",
        "description": "Disjuntor tripolar tipo DIN, corrente nominal de 32A a 63A, curva C — fornecimento e instalação",
        "unit": "UN",
        "category": "DISJUNTOR_TRIPOLAR",
        "unit_price_brl": 112.40,
        "reference_month": "2025-01",
        "state_uf": "SP",
        "material_specs_json": {"poles": 3, "curve": "C", "range_a": [32, 63]},
    },
    {
        "sinapi_code": "101877",
        "description": "Interruptor diferencial residual (IDR) bipolar 40A, sensibilidade 30mA — fornecimento e instalação",
        "unit": "UN",
        "category": "IDR_BIPOLAR",
        "unit_price_brl": 185.00,
        "reference_month": "2025-01",
        "state_uf": "SP",
        "material_specs_json": {"poles": 2, "rated_current_a": 40, "sensitivity_ma": 30},
    },
    {
        "sinapi_code": "101879",
        "description": "Interruptor diferencial residual (IDR) tetrapolar 63A, sensibilidade 30mA — fornecimento e instalação",
        "unit": "UN",
        "category": "IDR_TETRAPOLAR",
        "unit_price_brl": 268.00,
        "reference_month": "2025-01",
        "state_uf": "SP",
        "material_specs_json": {"poles": 4, "rated_current_a": 63, "sensitivity_ma": 30},
    },
    {
        "sinapi_code": "101884",
        "description": "Dispositivo de proteção contra surtos (DPS) Classe II, 275V, 20kA/45kA — fornecimento e instalação",
        "unit": "UN",
        "category": "DPS_CLASSE_II",
        "unit_price_brl": 96.80,
        "reference_month": "2025-01",
        "state_uf": "SP",
        "material_specs_json": {"dps_class": "II", "uc_v": 275, "imax_ka": 45},
    },
    {
        "sinapi_code": "91924",
        "description": "Cabo de cobre flexível isolado 1,5 mm², anti-chama 450/750V, para circuitos terminais — fornecimento e instalação",
        "unit": "M",
        "category": "CABO_1_5MM",
        "unit_price_brl": 3.45,
        "reference_month": "2025-01",
        "state_uf": "SP",
        "material_specs_json": {"section_mm2": 1.5, "insulation": "PVC_70C"},
    },
    {
        "sinapi_code": "91926",
        "description": "Cabo de cobre flexível isolado 2,5 mm², anti-chama 450/750V, para circuitos terminais — fornecimento e instalação",
        "unit": "M",
        "category": "CABO_2_5MM",
        "unit_price_brl": 4.95,
        "reference_month": "2025-01",
        "state_uf": "SP",
        "material_specs_json": {"section_mm2": 2.5, "insulation": "PVC_70C"},
    },
    {
        "sinapi_code": "91928",
        "description": "Cabo de cobre flexível isolado 4,0 mm², anti-chama 450/750V, para circuitos terminais — fornecimento e instalação",
        "unit": "M",
        "category": "CABO_4_0MM",
        "unit_price_brl": 7.60,
        "reference_month": "2025-01",
        "state_uf": "SP",
        "material_specs_json": {"section_mm2": 4.0, "insulation": "PVC_70C"},
    },
    {
        "sinapi_code": "91930",
        "description": "Cabo de cobre flexível isolado 6,0 mm², anti-chama 450/750V, para circuitos terminais — fornecimento e instalação",
        "unit": "M",
        "category": "CABO_6_0MM",
        "unit_price_brl": 11.20,
        "reference_month": "2025-01",
        "state_uf": "SP",
        "material_specs_json": {"section_mm2": 6.0, "insulation": "PVC_70C"},
    },
    {
        "sinapi_code": "91932",
        "description": "Cabo de cobre flexível isolado 10,0 mm², anti-chama 450/750V, para alimentação — fornecimento e instalação",
        "unit": "M",
        "category": "CABO_10_0MM",
        "unit_price_brl": 18.40,
        "reference_month": "2025-01",
        "state_uf": "SP",
        "material_specs_json": {"section_mm2": 10.0, "insulation": "PVC_70C"},
    },
    {
        "sinapi_code": "101860",
        "description": "Barramento isolado de cobre para Neutro ou Terra (PE), 12 bornes — fornecimento e instalação",
        "unit": "UN",
        "category": "BARRAMENTO_N_PE",
        "unit_price_brl": 48.50,
        "reference_month": "2025-01",
        "state_uf": "SP",
        "material_specs_json": {"terminals": 12},
    },
    {
        "sinapi_code": "101891",
        "description": "Placa de sinalização de advertência de risco elétrico NR-10 e porta-diagrama unifilar",
        "unit": "UN",
        "category": "SINALIZACAO_NR10",
        "unit_price_brl": 34.00,
        "reference_month": "2025-01",
        "state_uf": "SP",
        "material_specs_json": {"standard": "NR-10"},
    },
    {
        "sinapi_code": "88264",
        "description": "Eletricista com encargos complementares (adequação e revisão de quadro de distribuição)",
        "unit": "H",
        "category": "MAO_DE_OBRA_ELETRICISTA",
        "unit_price_brl": 42.30,
        "reference_month": "2025-01",
        "state_uf": "SP",
        "material_specs_json": {"role": "ELETRICISTA"},
    },
]


async def seed_sinapi_items(session: AsyncSession) -> int:
    """Idempotently insert or update SINAPI electrical items."""
    inserted = 0
    for item in SINAPI_ELETRICA_SEED:
        existing = await session.scalar(
            select(SinapiItem).where(SinapiItem.sinapi_code == item["sinapi_code"])
        )
        if existing is None:
            session.add(SinapiItem(**item))
            inserted += 1
        else:
            for field, value in item.items():
                setattr(existing, field, value)
    await session.flush()
    return inserted
