"""Narrador mock (v2, §5.3) — fallback y tests.

Plantillas mínimas sin dependencias, usadas en tests y como fallback si
falta el JSON de plantillas. El runtime conmuta a Mock automáticamente ante
esa ausencia, cerrando un riesgo de fiabilidad.
"""
from __future__ import annotations

from typing import Optional

from ..models import AnomalyEvent, AnomalyType, NarrationResult
from .base import LLMNarrator

_MINIMAL = {
    AnomalyType.NEGATIVE_QUANTITY: "Cantidad negativa anómala en {rack}.",
    AnomalyType.DURATION_OUTLIER: "Duración fuera de rango en {rack}.",
    AnomalyType.TRACEABILITY_BROKEN: "Trazabilidad rota en {rack}.",
    AnomalyType.UNKNOWN_RACK: "Ubicación desconocida: {rack}.",
}


class MockNarrator(LLMNarrator):
    """Genera narraciones mínimas determinísticas sin dependencias externas."""

    @property
    def model_name(self) -> str:
        return "mock-v1"

    async def is_available(self) -> bool:
        return True  # siempre disponible

    async def narrate(self, anomaly: AnomalyEvent) -> Optional[NarrationResult]:
        text = _MINIMAL.get(anomaly.type, "Anomalía detectada en {rack}.").format(
            rack=anomaly.rack_id
        )
        detail = anomaly.detail or text
        return NarrationResult(
            anomaly_id=anomaly.id,
            rack_id=anomaly.rack_id,
            text=text,
            likely_cause=detail,
            recommended_action="Revisar el evento con el supervisor de turno.",
            model=self.model_name,
            latency_ms=0.0,
        )
