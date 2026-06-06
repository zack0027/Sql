"""Severidad de una anomalía como enumeración con utilidades de parseo.

v2: tres niveles LOW/MEDIUM/HIGH, alineados con el mapeo de color del
cliente Unity (§7.2 de la documentación técnica v2):
  HIGH   → rojo HDR (activa Bloom)
  MEDIUM → ámbar
  LOW    → azul
"""
from __future__ import annotations

from enum import Enum


class Severity(str, Enum):
    """
    Severidad de una anomalía detectada.

    Hereda de str para serialización trivial a JSON y comparación directa
    con strings provenientes del frontend o de artefactos versionados.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

    @classmethod
    def parse(cls, raw: str | None) -> "Severity":
        """Tolerante a None, minúsculas y espacios. Default LOW."""
        if not raw:
            return cls.LOW
        try:
            return cls(raw.strip().upper())
        except ValueError:
            return cls.LOW

    @property
    def rank(self) -> int:
        """Orden numérico para comparaciones y umbrales."""
        return {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2}[self]

    def __ge__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, Severity):
            return self.rank >= other.rank
        return NotImplemented

    def __gt__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, Severity):
            return self.rank > other.rank
        return NotImplemented
