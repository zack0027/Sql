"""Modelos de dominio compartidos por todos los módulos (v2)."""
from .severity import Severity
from .movement import KNOWN_RACK_PATTERN, Movement, MovementType
from .anomaly import AnomalyEvent, AnomalyType
from .narrative import NarrationResult

__all__ = [
    "Severity",
    "Movement",
    "MovementType",
    "KNOWN_RACK_PATTERN",
    "AnomalyEvent",
    "AnomalyType",
    "NarrationResult",
]
