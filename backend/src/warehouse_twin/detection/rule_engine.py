"""
Motor de reglas de negocio para detectar anomalías obvias.

Diseño POO: Chain of Responsibility donde cada regla evalúa el
movimiento de forma aislada y devuelve un código si dispara.
Las reglas se componen en RuleEngine y se ejecutan en paralelo lógico
(todas se evalúan; el resultado es la unión).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from ..models import Movement


class Rule(ABC):
    """Interfaz abstracta de una regla de negocio."""

    @property
    @abstractmethod
    def code(self) -> str:
        """Código corto que aparece en rule_reasons. Ej: 'cantidad_negativa'."""

    @abstractmethod
    def evaluate(self, movement: Movement) -> Optional[str]:
        """
        Evalúa el movimiento.

        :return: el código si la regla dispara, None si no.
        """


class NegativeQuantityRule(Rule):
    """Una cantidad negativa solo tiene sentido en ajustes de inventario."""

    @property
    def code(self) -> str:
        return "cantidad_negativa"

    def evaluate(self, movement: Movement) -> Optional[str]:
        if movement.quantity < 0 and movement.movement_type not in ("ADJUSTMENT",):
            return self.code
        return None


class MinimumDurationRule(Rule):
    """Una inspección que toma 4 segundos no es una inspección real."""

    def __init__(self, min_seconds: int = 10):
        self.min_seconds = min_seconds

    @property
    def code(self) -> str:
        return "duracion_minima"

    def evaluate(self, movement: Movement) -> Optional[str]:
        if movement.movement_type == "INSPECTION" and movement.duration_sec < self.min_seconds:
            return self.code
        return None


class ExcessiveDurationRule(Rule):
    """Una operación que toma >5min indica bloqueo o problema técnico."""

    def __init__(self, max_seconds: int = 180):
        self.max_seconds = max_seconds

    @property
    def code(self) -> str:
        return "duracion_excesiva"

    def evaluate(self, movement: Movement) -> Optional[str]:
        if movement.duration_sec > self.max_seconds:
            return self.code
        return None


class OffHoursRule(Rule):
    """Operaciones fuera de horario laboral típico."""

    @property
    def code(self) -> str:
        return "fuera_horario"

    def evaluate(self, movement: Movement) -> Optional[str]:
        if movement.is_off_hours():
            return self.code
        return None


class RuleEngine:
    """
    Compone reglas y las ejecuta todas sobre cada movimiento.

    Patrón: composite + chain of responsibility.
    """

    def __init__(self, rules: List[Rule] | None = None):
        self.rules: List[Rule] = rules or [
            NegativeQuantityRule(),
            MinimumDurationRule(),
            ExcessiveDurationRule(),
            OffHoursRule(),
        ]

    def evaluate(self, movement: Movement) -> List[str]:
        """Devuelve la lista de códigos de reglas que dispararon."""
        return [code for r in self.rules if (code := r.evaluate(movement)) is not None]
