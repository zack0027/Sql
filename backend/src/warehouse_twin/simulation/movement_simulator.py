"""
Simulador que genera un stream continuo de movimientos hacia el broker.

Útil para la demo: mantiene el almacén "vivo" sin necesidad de un WMS real.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ..streaming import WebSocketBroker
from .anomaly_injector import AnomalyInjector

log = logging.getLogger(__name__)


class MovementSimulator:
    """
    Genera movimientos a una tasa configurable y los pasa al broker.

    Patrón: Producer en pipeline async. El consumer es el broker.
    """

    def __init__(
        self,
        broker: WebSocketBroker,
        injector: Optional[AnomalyInjector] = None,
        movements_per_second: float = 2.0,
        anomaly_ratio: float = 0.15,
    ):
        self.broker = broker
        self.injector = injector or AnomalyInjector()
        self.rate = movements_per_second
        self.anomaly_ratio = anomaly_ratio
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info("MovementSimulator started at %s mov/s", self.rate)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("MovementSimulator stopped")

    async def _run(self) -> None:
        interval = 1.0 / max(0.1, self.rate)
        try:
            while self._running:
                if self.injector.rng.random() < self.anomaly_ratio:
                    movement = self.injector.generate_anomaly()
                else:
                    movement = self.injector.generate_normal()

                await self.broker.process_movement(movement)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Simulator crashed")
