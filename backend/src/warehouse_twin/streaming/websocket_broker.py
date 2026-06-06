"""Broker del flujo runtime (v2, §8).

movimiento → detección → narración (plantilla, 0 ms) → broadcast.

Diseño POO: Mediator. Conoce a los tres colaboradores (detector, narrator,
manager) y coordina su interacción. Los colaboradores no se conocen entre sí.

Cambio v2: como el TemplateNarrator es instantáneo y determinista, la
narración deja de ser una tarea asíncrona en background. detect→narrate→
publish se completa en milisegundos (hipótesis H1: < 50 ms), eliminando el
acople de latencia del LLM que tenía la v1.
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional

from ..detection import AnomalyDetector
from ..models import AnomalyEvent, Movement
from ..narration import LLMNarrator
from .connection_manager import ConnectionManager

log = logging.getLogger(__name__)


class WebSocketBroker:
    """Mediator entre detección, narración y broadcast."""

    def __init__(
        self,
        detector: AnomalyDetector,
        narrator: LLMNarrator,
        manager: ConnectionManager,
        on_broadcast: Optional[Callable[[dict], None]] = None,
    ):
        self.detector = detector
        self.narrator = narrator
        self.manager = manager
        self._on_broadcast = on_broadcast

    async def process_movement(self, movement: Movement) -> List[AnomalyEvent]:
        """
        Punto de entrada principal. Llamado por el endpoint /movements
        o por el simulador interno. Devuelve las anomalías detectadas.
        """
        anomalies = self.detector.detect(movement)
        for anomaly in anomalies:
            await self._publish_anomaly(anomaly)
        return anomalies

    async def _publish_anomaly(self, anomaly: AnomalyEvent) -> None:
        # 1. Alerta (anomalía)
        payload = anomaly.to_websocket_payload()
        await self.manager.broadcast(payload)
        if self._on_broadcast:
            self._on_broadcast(payload)

        # 2. Narración determinista (latencia cero) en el mismo ciclo
        try:
            narration = await self.narrator.narrate(anomaly)
            if narration is not None:
                await self.manager.broadcast(narration.to_websocket_payload())
        except Exception:
            log.exception("Narración falló para anomalía %s", anomaly.id)

    async def shutdown(self) -> None:
        """Sin tareas en background que esperar en v2. Hook de cierre limpio."""
        return None
