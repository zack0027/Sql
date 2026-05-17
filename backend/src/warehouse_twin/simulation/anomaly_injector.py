"""
Inyector de anomalías sintéticas para el simulator.

Genera movimientos que el detector debe marcar como anómalos.
Útil para demo, tests, y benchmark del detector.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from ..models import Movement


class AnomalyInjector:
    """Genera movimientos sintéticos con patrones de anomalía conocidos."""

    MOVEMENT_TYPES = ["RECEIVING", "INSPECTION", "PUTAWAY", "PICK", "ORDER", "TRACEABILITY", "MAQUILA"]

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)

    def _location(self) -> str:
        row = chr(ord("A") + self.rng.randint(0, 5))
        col = self.rng.randint(1, 18)
        return f"{row}-{col:03d}"

    def _sku(self) -> str:
        return f"MX-{self.rng.randint(1, 99):04d}"

    def _user(self) -> str:
        return f"USR_{self.rng.randint(1, 60):03d}"

    def _now_offset(self, seconds: int) -> datetime:
        return datetime.now() - timedelta(seconds=seconds)

    def generate_normal(self) -> Movement:
        """Movimiento normal (no debe disparar reglas)."""
        return Movement(
            movement_id=f"MV-{self.rng.randint(100000, 999999)}",
            timestamp=self._now_offset(self.rng.randint(0, 60)),
            movement_type=self.rng.choice(self.MOVEMENT_TYPES),
            sku=self._sku(),
            location=self._location(),
            user_id=self._user(),
            quantity=self.rng.randint(1, 80),
            duration_sec=self.rng.randint(15, 120),
        )

    def generate_anomaly(self, kind: str | None = None) -> Movement:
        """
        Movimiento con anomalía sintética.

        :param kind: 'short_duration' | 'long_duration' | 'negative_qty' | 'off_hours'
                    None = aleatorio entre las 4.
        """
        kinds = ["short_duration", "long_duration", "negative_qty", "off_hours"]
        kind = kind or self.rng.choice(kinds)

        base = self.generate_normal()

        if kind == "short_duration":
            base.movement_type = "INSPECTION"
            base.duration_sec = self.rng.randint(2, 9)
        elif kind == "long_duration":
            base.duration_sec = self.rng.randint(200, 600)
        elif kind == "negative_qty":
            base.movement_type = "INSPECTION"
            base.quantity = -self.rng.randint(1, 5)
        elif kind == "off_hours":
            base.timestamp = base.timestamp.replace(hour=3, minute=15)

        return base
