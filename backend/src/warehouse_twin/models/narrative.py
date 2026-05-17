"""Narrativa generada por el LLM para acompañar una anomalía."""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class Narrative(BaseModel):
    """
    Explicación en lenguaje natural de una anomalía.

    Se produce de forma asíncrona después del Anomaly, en un segundo
    broadcast al cliente Unity. El cliente correlaciona con el movement_id.
    """

    movement_id: str
    location: str
    narrative: str = Field(..., description="Resumen humano de lo que pasó")
    likely_cause: str = Field(..., description="Hipótesis de causa raíz")
    recommended_action: str = Field(..., description="Acción concreta sugerida")
    source: str = Field(..., description="'ollama' | 'mock' | 'replay'")
    model: str = Field(..., description="Nombre del modelo, ej. 'llama-3.2-3b'")
    latency_sec: float = Field(..., ge=0.0)
    emitted_at: datetime = Field(default_factory=datetime.now)

    def to_websocket_payload(self) -> dict:
        return {
            "type": "narrative",
            "movement_id": self.movement_id,
            "location": self.location,
            "narrative": self.narrative,
            "likely_cause": self.likely_cause,
            "recommended_action": self.recommended_action,
            "source": self.source,
            "model": self.model,
            "latency_sec": self.latency_sec,
            "emitted_at": self.emitted_at.isoformat(sep=" ", timespec="seconds"),
        }
