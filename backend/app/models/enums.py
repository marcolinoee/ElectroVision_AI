"""Domain enumerations shared across ORM models and Pydantic contracts."""

from enum import StrEnum


class InspectionStatus(StrEnum):
    """Rigid CREA/ART sign-off state machine."""

    DRAFT = "DRAFT"
    AI_PROCESSED = "AI_PROCESSED"
    ENGINEER_VALIDATED = "ENGINEER_VALIDATED"
    EXPORTED = "EXPORTED"


class ComponentType(StrEnum):
    """Electrical panel & distribution component taxonomy."""

    DISJUNTOR_GERAL = "DISJUNTOR_GERAL"
    DISJUNTOR_CIRCUITO = "DISJUNTOR_CIRCUITO"
    IDR = "IDR"
    DPS = "DPS"
    BARRAMENTO_FASE = "BARRAMENTO_FASE"
    BARRAMENTO_NEUTRO = "BARRAMENTO_NEUTRO"
    BARRAMENTO_TERRA = "BARRAMENTO_TERRA"
    CABO_FASE = "CABO_FASE"
    CABO_NEUTRO = "CABO_NEUTRO"
    CABO_TERRA = "CABO_TERRA"
    CONTATOR = "CONTATOR"
    RELE_TERMICO = "RELE_TERMICO"
    MEDIDOR = "MEDIDOR"
    QUADRO_DISTRIBUICAO = "QUADRO_DISTRIBUICAO"
    OUTRO = "OUTRO"


class SupplySystem(StrEnum):
    """Brazilian low/medium voltage supply systems."""

    MONOFASICO_127V = "MONOFASICO_127V"
    MONOFASICO_220V = "MONOFASICO_220V"
    BIFASICO_127_220V = "BIFASICO_127_220V"
    TRIFASICO_220_127V = "TRIFASICO_220_127V"
    TRIFASICO_380_220V = "TRIFASICO_380_220V"
    MEDIA_TENSAO_13_8KV = "MEDIA_TENSAO_13_8KV"


class GroundingScheme(StrEnum):
    """NBR 5410 grounding schemes."""

    TN_S = "TN_S"
    TN_C = "TN_C"
    TN_C_S = "TN_C_S"
    TT = "TT"
    IT = "IT"


class TripCurve(StrEnum):
    """Miniature circuit breaker trip curves (IEC 60898 / NBR NM 60898)."""

    B = "B"
    C = "C"
    D = "D"


class CableColor(StrEnum):
    """Standardized conductor insulation colors (NBR 5410 section 6.1.5.3)."""

    AZUL_CLARO = "AZUL_CLARO"
    VERDE = "VERDE"
    VERDE_AMARELO = "VERDE_AMARELO"
    PRETO = "PRETO"
    VERMELHO = "VERMELHO"
    BRANCO = "BRANCO"
    CINZA = "CINZA"
    MARROM = "MARROM"
    AMARELO = "AMARELO"
    DESCONHECIDA = "DESCONHECIDA"


class SeverityLevel(StrEnum):
    """Non-conformity severity levels."""

    CRITICA = "CRITICA"
    ALTA = "ALTA"
    MEDIA = "MEDIA"
    BAIXA = "BAIXA"
    INFORMATIVA = "INFORMATIVA"


class ArtifactType(StrEnum):
    """Official exportable engineering artifacts."""

    UNIFILAR_DXF = "UNIFILAR_DXF"
    UNIFILAR_SVG = "UNIFILAR_SVG"
    PLANTA_DXF = "PLANTA_DXF"
    MEMORIAL_DOCX = "MEMORIAL_DOCX"
    RETROFIT_XLSX = "RETROFIT_XLSX"


class DatasetSplit(StrEnum):
    """Active Learning dataset partitions."""

    TRAIN = "train"
    VAL = "val"
    GOLDEN_HOLDOUT = "golden_holdout"
