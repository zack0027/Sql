"""Anomalía detectada: output del módulo detection.

v2 (§4.4 y §9): la anomalía deja de ser un wrapper del movimiento con
flag `is_anomaly`. Ahora `AnomalyEvent` es un evento de primera clase con
un `id` propio, su `type` tipado (AnomalyType) y `detail` textual. El
detector devuelve `list[AnomalyEvent]` (vacía cuando no hay anomalía),
de modo que un mismo movimiento puede producir varias.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from .severity import Severity


class AnomalyType(str, Enum):
    """Catálogo cerrado de anomalías que el sistema sabe reconocer (v2)."""

    NEGATIVE_QUANTITY = "NEGATIVE_QUANTITY"
    DURATION_OUTLIER = "DURATION_OUTLIER"
    TRACEABILITY_BROKEN = "TRACEABILITY_BROKEN"
    UNKNOWN_RACK = "UNKNOWN_RACK"


class AnomalyEvent(BaseModel):
    """
    Una anomalía concreta detectada en un movimiento.

    Lleva todo lo que los eslabones siguientes (narrador, broker, UI)
    necesitan: a qué movimiento y rack pertenece, su tipo y severidad,
    y un `detail` legible. La narración se correlaciona por `id`.
    """

    id: str = Field(default_factory=lambda: f"AN-{uuid.uuid4().hex[:12]}")
    movement_id: str = Field(..., description="id del Movement que la originó")
    rack_id: str = Field(..., description="Ubicación afectada")
    type: AnomalyType = Field(..., description="Tipo de anomalía")
    severity: Severity = Field(default=Severity.MEDIUM)
    detail: str = Field(default="", description="Descripción legible de la evidencia")
    detector: str = Field(default="rule", description="Origen: 'rule' | 'ml'")
    timestamp: datetime = Field(default_factory=datetime.now)

    def to_websocket_payload(self) -> dict:
        """
        Serializa al formato que espera el cliente (Unity / dashboard web).

        Plano (sin anidamiento) para que JsonUtility de Unity lo parsee.
        Las keys deben coincidir 1-a-1 con WMSMessage.cs.
        """
        return {
            "type": "anomaly",
            "id": self.id,
            "movement_id": self.movement_id,
            "rack_id": self.rack_id,
            "anomaly_type": self.type.value,
            "severity": self.severity.value,
            "detail": self.detail,
            "detector": self.detector,
            "timestamp": self.timestamp.isoformat(sep=" ", timespec="seconds"),
        }
