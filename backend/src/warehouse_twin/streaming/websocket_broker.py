"""
Broker que orquesta el flujo completo: movimiento → detección → broadcast
alerta → narración asíncrona → broadcast narrativa.

Diseño POO: Mediator. Conoce a los tres colaboradores (detector, narrator,
manager) y coordina su interacción. Los colaboradores no se conocen entre sí.
"""
from __future__ import annotations

import asyncio
import logging

from ..detection import AnomalyDetector
from ..models import Movement
from ..narration import LLMNarrator
from .connection_manager import ConnectionManager

log = logging.getLogger(__name__)


class WebSocketBroker:
    """
    Mediator entre detección, narración y broadcast.

    Garantiza:
      1. La alerta llega al cliente Unity inmediatamente (< 10ms post detect).
      2. La narrativa LLM se procesa en background sin bloquear el stream.
      3. La narrativa llega al cliente 1-5s después con el mismo movement_id
         para que el cliente correlacione.
    """

    def __init__(
        self,
        detector: AnomalyDetector,
        narrator: LLMNarrator,
        manager: ConnectionManager,
    ):
        self.detector = detector
        self.narrator = narrator
        self.manager = manager
        self._narration_tasks: set[asyncio.Task] = set()

    async def process_movement(self, movement: Movement) -> None:
        """
        Punto de entrada principal. Llamado por el endpoint /ingest
        o por el simulator interno.
        """
        anomaly = self.detector.detect(movement)
        if not anomaly.is_anomaly:
            return  # movimientos normales no se broadcastean

        # 1. Alerta inmediata
        await self.manager.broadcast(anomaly.to_websocket_payload())

        # 2. Narración en background (fire and forget con tracking)
        task = asyncio.create_task(self._narrate_and_broadcast(anomaly))
        self._narration_tasks.add(task)
        task.add_done_callback(self._narration_tasks.discard)

    async def _narrate_and_broadcast(self, anomaly) -> None:
        try:
            narrative = await self.narrator.generate(anomaly)
            if narrative is not None:
                await self.manager.broadcast(narrative.to_websocket_payload())
        except Exception:
            log.exception("Narration failed for movement %s", anomaly.movement.movement_id)

    async def shutdown(self) -> None:
        """Espera que terminen las narraciones pendientes al cerrar el server."""
        if self._narration_tasks:
            await asyncio.gather(*self._narration_tasks, return_exceptions=True)
