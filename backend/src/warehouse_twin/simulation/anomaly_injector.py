"""Inyector de movimientos sintéticos (v2, §6.4).

Genera movimientos normales y anómalos, devolviendo el GROUND TRUTH (qué
tipos de anomalía contiene cada movimiento) para evaluación con F1. Cubre los
cuatro tipos del catálogo v2 y añade:
  - duration_s real (habilita DURATION_OUTLIER),
  - anomalías contextuales (cantidad normal pero anómala para ese rack/hora),
  - deriva temporal (drift) que vuelve obsoleto un umbral fijo.

FUNDAMENTO: la robustez ante drift de las reglas destiladas la documentan
Zhang y Jain (Amazon); el estándar de evaluación por F1 sobre ground truth lo
fija Xu, Ali y Yue (LATTICE, Simula / U. Oslo).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List

from ..models import AnomalyType, Movement, MovementType


@dataclass
class LabeledMovement:
    """Movimiento + su ground truth (tipos de anomalía que realmente contiene)."""

    movement: Movement
    labels: List[AnomalyType] = field(default_factory=list)

    @property
    def is_anomaly(self) -> bool:
        return bool(self.labels)


_MOVEMENT_TYPES = [
    MovementType.RECEIVING,
    MovementType.INSPECTION,
    MovementType.PUTAWAY,
    MovementType.PICK,
    MovementType.ORDER,
    MovementType.TRACEABILITY,
    MovementType.MAQUILA,
]


class AnomalyInjector:
    """Genera movimientos sintéticos con patrones de anomalía conocidos."""

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self._counter = 0
        # Factor de deriva: crece lentamente y desplaza la duración "normal".
        self._drift = 0.0

    # ── helpers de campos ────────────────────────────────────────────────
    def _next_id(self) -> str:
        self._counter += 1
        return f"MV-{self._counter:06d}-{self.rng.randint(1000, 9999)}"

    def _known_rack(self) -> str:
        row = chr(ord("A") + self.rng.randint(0, 5))
        col = self.rng.randint(1, 18)
        return f"{row}-{col:03d}"

    def _unknown_rack(self) -> str:
        # Fuera del layout canónico A-F / 001-018.
        return self.rng.choice(["Z-999", "X-000", "Q-042", "A-099", "MAQ-PLT-04"])

    def _sku(self) -> str:
        return f"MX-{self.rng.randint(1, 99):04d}"

    def _user(self) -> str:
        return f"USR_{self.rng.randint(1, 60):03d}"

    def _now_offset(self, seconds: int) -> datetime:
        return datetime.now() - timedelta(seconds=seconds)

    def advance_drift(self, amount: float = 0.5) -> None:
        """Avanza la deriva temporal (llamado por el simulador con el tiempo)."""
        self._drift += amount

    # ── generación ───────────────────────────────────────────────────────
    def generate_normal(self) -> Movement:
        """Movimiento normal: no debe disparar ninguna regla."""
        base_duration = self.rng.uniform(15, 120) + self._drift
        return Movement(
            id=self._next_id(),
            rack_id=self._known_rack(),
            movement_type=self.rng.choice(_MOVEMENT_TYPES),
            quantity=self.rng.randint(1, 80),
            duration_s=round(base_duration, 1),
            timestamp=self._now_offset(self.rng.randint(0, 60)),
            sku=self._sku(),
            user_id=self._user(),
        )

    def generate_normal_labeled(self) -> LabeledMovement:
        return LabeledMovement(self.generate_normal(), [])

    def generate_anomaly_labeled(self, kind: str | None = None) -> LabeledMovement:
        """
        Movimiento con anomalía sintética y su etiqueta (ground truth).

        kinds: 'negative_qty' | 'duration_short' | 'duration_long' |
               'traceability' | 'unknown_rack' | 'contextual'
        """
        kinds = [
            "negative_qty",
            "duration_short",
            "duration_long",
            "traceability",
            "unknown_rack",
            "contextual",
        ]
        kind = kind or self.rng.choice(kinds)
        m = self.generate_normal()
        labels: List[AnomalyType] = []

        if kind == "negative_qty":
            m.movement_type = MovementType.INSPECTION
            m.quantity = -self.rng.randint(1, 5)
            labels.append(AnomalyType.NEGATIVE_QUANTITY)
        elif kind == "duration_short":
            m.movement_type = MovementType.INSPECTION
            m.duration_s = float(self.rng.randint(2, 9))
            labels.append(AnomalyType.DURATION_OUTLIER)
        elif kind == "duration_long":
            m.duration_s = float(self.rng.randint(200, 600))
            labels.append(AnomalyType.DURATION_OUTLIER)
        elif kind == "traceability":
            m.movement_type = MovementType.TRACEABILITY
            m.quantity = 0
            labels.append(AnomalyType.TRACEABILITY_BROKEN)
        elif kind == "unknown_rack":
            m.rack_id = self._unknown_rack()
            labels.append(AnomalyType.UNKNOWN_RACK)
        elif kind == "contextual":
            # Duración "normal" en valor absoluto pero que excede el máximo por
            # efecto de la deriva acumulada: terreno donde el ML supera al umbral.
            m.duration_s = round(self.rng.uniform(150, 210) + self._drift, 1)
            if m.duration_s > 180:
                labels.append(AnomalyType.DURATION_OUTLIER)

        return LabeledMovement(m, labels)

    # ── compatibilidad con la API previa ─────────────────────────────────
    def generate_anomaly(self, kind: str | None = None) -> Movement:
        return self.generate_anomaly_labeled(kind).movement
