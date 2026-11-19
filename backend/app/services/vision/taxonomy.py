"""Pure-Python canonical YOLO class taxonomy shared by api, worker-ml, and tests (no numpy/cv2)."""

from app.models.enums import ComponentType

# Canonical class ID mapping shared across YOLO inference, dataset export, and Golden Holdout eval
CANONICAL_YOLO_CLASSES: dict[int, ComponentType] = {
    0: ComponentType.DISJUNTOR_GERAL,
    1: ComponentType.DISJUNTOR_CIRCUITO,
    2: ComponentType.IDR,
    3: ComponentType.DPS,
    4: ComponentType.BARRAMENTO_FASE,
    5: ComponentType.BARRAMENTO_NEUTRO,
    6: ComponentType.BARRAMENTO_TERRA,
    7: ComponentType.CABO_FASE,
    8: ComponentType.CABO_NEUTRO,
    9: ComponentType.CABO_TERRA,
    10: ComponentType.CONTATOR,
    11: ComponentType.RELE_TERMICO,
    12: ComponentType.MEDIDOR,
    13: ComponentType.QUADRO_DISTRIBUICAO,
}

COMPONENT_TYPE_TO_YOLO_CLASS_ID: dict[ComponentType, int] = {
    comp_type: class_id for class_id, comp_type in CANONICAL_YOLO_CLASSES.items()
}

# Critical safety classes that MUST maintain Recall >= 0.95 on Golden Holdout Set
CRITICAL_PROTECTION_CLASSES: set[ComponentType] = {
    ComponentType.IDR,
    ComponentType.DPS,
    ComponentType.DISJUNTOR_GERAL,
    ComponentType.DISJUNTOR_CIRCUITO,
}
