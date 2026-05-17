"""Severidad de anomalía como enumeración con utilidades de parseo."""
from __future__ import annotations

from enum import Enum


class Severity(str, Enum):
    """
    Severidad de una anomalía.

    Hereda de str para que sea trivialmente serializable a JSON y
    comparable con strings que vienen del frontend o de la base de datos.
    """

    NORMAL = "normal"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def parse(cls, raw: str | None) -> "Severity":
        """Tolerante a None, mayúsculas, espacios."""
        if not raw:
            return cls.NORMAL
        try:
            return cls(raw.strip().lower())
        except ValueError:
            return cls.NORMAL

    @property
    def rank(self) -> int:
        """Orden numérico para comparaciones y umbrales."""
        return {
            Severity.NORMAL: 0,
            Severity.MEDIUM: 1,
            Severity.HIGH: 2,
            Severity.CRITICAL: 3,
        }[self]

    def __ge__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, Severity):
            return self.rank >= other.rank
        return NotImplemented
