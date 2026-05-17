"""Anomalía detectada: output del módulo detection."""
from __future__ import annotations

from typing import List
from pydantic import BaseModel, Field

from .movement import Movement
from .severity import Severity


class Anomaly(BaseModel):
    """
    Una anomalía detectada en un movimiento.

    Combina el movimiento original con la decisión del detector
    (severidad, score, reglas que disparó) para que el siguiente eslabón
    de la cadena (narrador, broker WebSocket) tenga toda la info.
    """

    movement: Movement
    severity: Severity
    score: float = Field(..., ge=0.0, le=1.0, description="Confianza del modelo IA")
    is_anomaly: bool = Field(...)
    rule_reasons: List[str] = Field(
        default_factory=list,
        description="Reglas humanas que dispararon, ej. 'cantidad_negativa'",
    )

    def to_websocket_payload(self) -> dict:
        """
        Serializa al formato que espera el cliente Unity.

        Aplana movement.* al top-level para que JsonUtility de Unity pueda
        parsearlo sin campos anidados. Las keys aquí deben coincidir 1-a-1
        con WMSMessage.cs.
        """
        return {
            "type": "alert",
            "movement_id": self.movement.movement_id,
            "timestamp": self.movement.timestamp.isoformat(sep=" ", timespec="seconds"),
            "movement_type": self.movement.movement_type,
            "sku": self.movement.sku,
            "location": self.movement.location,
            "user_id": self.movement.user_id,
            "quantity": self.movement.quantity,
            "duration_sec": self.movement.duration_sec,
            "severity": self.severity.value,
            "is_anomaly": self.is_anomaly,
            "rule_reasons": ", ".join(self.rule_reasons),
        }
