"""Contrato abstracto del módulo de detección (v2, §4).

Una clase base abstracta `AnomalyDetector` define el contrato; las
implementaciones concretas (reglas, ML, híbrido) lo cumplen sin conocerse
entre sí. Devuelven `list[AnomalyEvent]` (vacía si no hay anomalía), de
modo que un mismo movimiento puede producir varias.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..models import AnomalyEvent, Movement


class AnomalyDetector(ABC):
    """Contrato que todo detector debe satisfacer."""

    @abstractmethod
    def detect(self, movement: Movement) -> List[AnomalyEvent]:
        """Evalúa un movimiento y devuelve las anomalías encontradas."""
