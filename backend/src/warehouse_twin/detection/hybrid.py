"""Detector híbrido (v2, §4.3).

`HybridDetector` compone reglas y ML bajo la misma interfaz, deduplicando
anomalías. Es el 'híbrido' real: reglas rápidas e interpretables para lo
evidente, ML para lo sutil.
"""
from __future__ import annotations

from typing import List, Tuple

from ..models import AnomalyEvent, Movement
from .base import AnomalyDetector


class HybridDetector(AnomalyDetector):
    """Composite de detectores que deduplica por (movement_id, type)."""

    def __init__(self, detectors: List[AnomalyDetector]):
        self._detectors = detectors

    def detect(self, movement: Movement) -> List[AnomalyEvent]:
        seen: set[Tuple[str, str]] = set()
        out: List[AnomalyEvent] = []
        for det in self._detectors:
            for anomaly in det.detect(movement):
                key = (anomaly.movement_id, anomaly.type.value)
                if key not in seen:
                    seen.add(key)
                    out.append(anomaly)
        return out
