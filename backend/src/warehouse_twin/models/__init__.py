"""Modelos de dominio compartidos por todos los módulos."""
from .severity import Severity
from .movement import Movement
from .anomaly import Anomaly
from .narrative import Narrative

__all__ = ["Severity", "Movement", "Anomaly", "Narrative"]
