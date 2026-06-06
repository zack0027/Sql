"""Narración de una anomalía.

v2 (§5.1): la narración runtime ya NO la genera un LLM en vivo. La produce
el TemplateNarrator a partir de plantillas pre-generadas offline, con
latencia cero y salida determinista. El contrato núcleo es el del doc:
`anomaly_id`, `text`, `model`, `latency_ms`. Se añaden campos opcionales
(`rack_id`, `likely_cause`, `recommended_action`) para enriquecer la UI
sin romper el contrato mínimo.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class NarrationResult(BaseModel):
    """Explicación en lenguaje natural de una anomalía, correlacionada por anomaly_id."""

    anomaly_id: str = Field(..., description="id del AnomalyEvent que explica")
    text: str = Field(..., description="Explicación principal en lenguaje natural")
    model: str = Field(..., description="Origen de la plantilla, ej. 'template-v1'")
    latency_ms: float = Field(default=0.0, ge=0.0)

    # Campos opcionales de enriquecimiento para la UI
    rack_id: str | None = Field(default=None, description="Ubicación afectada")
    likely_cause: str | None = Field(default=None, description="Hipótesis de causa raíz")
    recommended_action: str | None = Field(default=None, description="Acción sugerida")
    emitted_at: datetime = Field(default_factory=datetime.now)

    def to_websocket_payload(self) -> dict:
        return {
            "type": "narration",
            "anomaly_id": self.anomaly_id,
            "rack_id": self.rack_id,
            "text": self.text,
            "likely_cause": self.likely_cause,
            "recommended_action": self.recommended_action,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "emitted_at": self.emitted_at.isoformat(sep=" ", timespec="seconds"),
        }
