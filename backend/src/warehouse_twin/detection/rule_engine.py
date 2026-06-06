"""Detector por reglas (v2, §4.1).

`RuleBasedDetector` orquesta reglas individuales, cada una una clase con
un único método `evaluate()`. Patrón Strategy (regla intercambiable) +
Composite (el detector las orquesta): agregar una regla no modifica al
orquestador.

FUNDAMENTO: el modelo rule-based como núcleo del gemelo de almacén proviene
de Chen, Chu, Yang, Wang y Xue (Suzhou City University; Hohai University).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from ..models import AnomalyEvent, AnomalyType, Movement, MovementType, Severity
from .base import AnomalyDetector


class Rule(ABC):
    """Interfaz abstracta de una regla de negocio (Strategy)."""

    @abstractmethod
    def evaluate(self, movement: Movement) -> Optional[AnomalyEvent]:
        """Devuelve un AnomalyEvent si la regla dispara, None si no."""

    @staticmethod
    def _event(
        movement: Movement,
        atype: AnomalyType,
        severity: Severity,
        detail: str,
    ) -> AnomalyEvent:
        return AnomalyEvent(
            movement_id=movement.id,
            rack_id=movement.rack_id,
            type=atype,
            severity=severity,
            detail=detail,
            detector="rule",
        )


class NegativeQuantityRule(Rule):
    """Una cantidad negativa solo tiene sentido en ajustes de inventario."""

    def evaluate(self, movement: Movement) -> Optional[AnomalyEvent]:
        if movement.quantity < 0 and movement.movement_type is not MovementType.ADJUSTMENT:
            return self._event(
                movement,
                AnomalyType.NEGATIVE_QUANTITY,
                Severity.HIGH,
                f"Cantidad negativa ({movement.quantity}) en movimiento "
                f"{movement.movement_type.value} sobre {movement.rack_id}.",
            )
        return None


class DurationOutlierRule(Rule):
    """Duraciones fuera de rango: inspección demasiado corta o operación bloqueada."""

    def __init__(self, min_inspection_s: float = 10.0, max_s: float = 180.0):
        self.min_inspection_s = min_inspection_s
        self.max_s = max_s

    def evaluate(self, movement: Movement) -> Optional[AnomalyEvent]:
        if movement.duration_s is None:
            return None
        if movement.duration_s > self.max_s:
            return self._event(
                movement,
                AnomalyType.DURATION_OUTLIER,
                Severity.HIGH,
                f"Duración {movement.duration_s:.0f}s supera el máximo "
                f"({self.max_s:.0f}s); posible bloqueo.",
            )
        if (
            movement.movement_type is MovementType.INSPECTION
            and movement.duration_s < self.min_inspection_s
        ):
            return self._event(
                movement,
                AnomalyType.DURATION_OUTLIER,
                Severity.MEDIUM,
                f"Inspección de {movement.duration_s:.0f}s por debajo del "
                f"mínimo creíble ({self.min_inspection_s:.0f}s).",
            )
        return None


class TraceabilityRule(Rule):
    """Trazabilidad rota: un movimiento de trazabilidad sin lote/entrada asociada."""

    def evaluate(self, movement: Movement) -> Optional[AnomalyEvent]:
        if movement.movement_type is MovementType.TRACEABILITY and movement.quantity <= 0:
            return self._event(
                movement,
                AnomalyType.TRACEABILITY_BROKEN,
                Severity.HIGH,
                f"Trazabilidad rota en {movement.rack_id}: sin entrada/ASN "
                "asociado al lote.",
            )
        return None


class UnknownRackRule(Rule):
    """Un movimiento sobre un rack fuera del layout canónico del almacén."""

    def evaluate(self, movement: Movement) -> Optional[AnomalyEvent]:
        if not movement.is_known_rack():
            return self._event(
                movement,
                AnomalyType.UNKNOWN_RACK,
                Severity.LOW,
                f"Ubicación desconocida '{movement.rack_id}' fuera del layout.",
            )
        return None


def default_rules() -> List[Rule]:
    """Conjunto de reglas por defecto (las 'destiladas' viven en este orden)."""
    return [
        NegativeQuantityRule(),
        DurationOutlierRule(),
        TraceabilityRule(),
        UnknownRackRule(),
    ]


class RuleBasedDetector(AnomalyDetector):
    """
    Compone reglas y las ejecuta todas sobre cada movimiento.

    Patrón: Composite + Strategy. El resultado es la unión de las
    anomalías que dispararon.
    """

    def __init__(self, rules: Optional[List[Rule]] = None):
        self._rules: List[Rule] = rules if rules is not None else default_rules()

    def detect(self, movement: Movement) -> List[AnomalyEvent]:
        return [
            event
            for rule in self._rules
            if (event := rule.evaluate(movement)) is not None
        ]
