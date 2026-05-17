"""
Narrador mock con templates determinísticos.

No requiere Ollama instalado: usa diccionario de plantillas curadas
por tipo de movimiento. Es el fallback que garantiza que la demo
funcione siempre, incluso sin conexión a un LLM.
"""
from __future__ import annotations

import time
from typing import Optional

from ..models import Anomaly, Narrative
from .base import LLMNarrator


_TEMPLATES = {
    "INSPECTION": {
        "narrative": (
            "Movimiento de inspección con patrón irregular detectado en {loc}. "
            "El operario registró duración inusual ({dur}s) sobre el SKU {sku}."
        ),
        "likely_cause": (
            "Posible bloqueo del proceso de inspección o falta de actualización "
            "del estado en sistema."
        ),
        "recommended_action": (
            "Verificar físicamente el rack y revisar el último login del usuario asignado."
        ),
    },
    "PUTAWAY": {
        "narrative": (
            "Tarea de putaway en {loc} con desviación respecto al algoritmo de "
            "ubicación óptima para el SKU {sku}."
        ),
        "likely_cause": (
            "El sistema sugirió otra ubicación pero el operario la sobrescribió manualmente."
        ),
        "recommended_action": (
            "Revisar la regla de slotting y validar capacidad del rack destino."
        ),
    },
    "PICK": {
        "narrative": (
            "Picking prolongado en {loc} para el SKU {sku}. Duración registrada: "
            "{dur}s, más del triple del baseline."
        ),
        "likely_cause": (
            "Producto difícil de localizar, falta de stock parcial, o pickeo con "
            "el equipo equivocado."
        ),
        "recommended_action": (
            "Confirmar inventario físico y reportar al supervisor de turno."
        ),
    },
    "TRACEABILITY": {
        "narrative": (
            "Trazabilidad rota en {loc}: el lote del SKU {sku} no tiene ASN ni "
            "movimiento de entrada asociado."
        ),
        "likely_cause": (
            "Recepción no registrada en sistema, o lote ingresado por proceso "
            "paralelo no auditado."
        ),
        "recommended_action": (
            "Bloquear el lote y abrir investigación con calidad para validar origen."
        ),
    },
    "RECEIVING": {
        "narrative": (
            "Recepción en {loc} con cantidad reportada ({qty}) diferente a la "
            "esperada en ASN para el SKU {sku}."
        ),
        "likely_cause": (
            "Discrepancia con el proveedor o conteo manual erróneo en la rampa."
        ),
        "recommended_action": (
            "Detener recepción, recontar, y abrir caso si la diferencia persiste."
        ),
    },
    "MAQUILA": {
        "narrative": (
            "Operación de maquila en {loc} resultó en stock negativo para el SKU {sku}."
        ),
        "likely_cause": (
            "Falta una entrada de transformación o el BOM del producto está mal "
            "configurado."
        ),
        "recommended_action": (
            "Pausar la línea, revisar BOM en sistema y registrar la entrada faltante."
        ),
    },
    "ORDER": {
        "narrative": (
            "Orden de trabajo asignada al rack {loc} sin progreso por más de 5 minutos."
        ),
        "likely_cause": (
            "Operario ausente, equipo de scanning con falla, o tarea bloqueada por "
            "otra OT activa."
        ),
        "recommended_action": (
            "Reasignar tarea o liberar las dependencias bloqueantes desde la consola "
            "del supervisor."
        ),
    },
}


class MockNarrator(LLMNarrator):
    """Genera narrativas determinísticas a partir de plantillas."""

    @property
    def source_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "template-v1"

    async def is_available(self) -> bool:
        return True  # siempre disponible

    async def generate(self, anomaly: Anomaly) -> Optional[Narrative]:
        start = time.perf_counter()
        m = anomaly.movement
        template = _TEMPLATES.get(m.movement_type, _TEMPLATES["INSPECTION"])

        return Narrative(
            movement_id=m.movement_id,
            location=m.location,
            narrative=template["narrative"].format(
                loc=m.location, dur=m.duration_sec, sku=m.sku, qty=m.quantity
            ),
            likely_cause=template["likely_cause"],
            recommended_action=template["recommended_action"],
            source=self.source_name,
            model=self.model_name,
            latency_sec=round(time.perf_counter() - start, 3),
        )
