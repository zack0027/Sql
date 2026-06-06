"""Cadena de narradores con fallback (v2).

Intenta una cadena de backends en orden y devuelve la primera narración
exitosa. En runtime la cadena estándar es TemplateNarrator → MockNarrator:
ambos deterministas y de latencia cero, sin LLM en vivo. Si el JSON de
plantillas falta, TemplateNarrator no se construye y queda solo Mock
(cierra el riesgo de fiabilidad descrito en §5.3).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from ..models import AnomalyEvent, NarrationResult
from .base import LLMNarrator
from .mock_narrator import MockNarrator

log = logging.getLogger(__name__)


class FallbackNarrator(LLMNarrator):
    """
    Cadena de narradores. Intenta cada uno en orden.

    Patrón: Chain of Responsibility con fallback automático. Si un backend
    falla o devuelve None, sigue con el siguiente. El último siempre debería
    ser MockNarrator (garantiza no-null).
    """

    def __init__(self, backends: List[LLMNarrator]):
        if not backends:
            raise ValueError("FallbackNarrator necesita al menos un backend")
        self.backends = backends

    @property
    def model_name(self) -> str:
        return ",".join(b.model_name for b in self.backends)

    async def is_available(self) -> bool:
        for b in self.backends:
            if await b.is_available():
                return True
        return False

    async def narrate(self, anomaly: AnomalyEvent) -> Optional[NarrationResult]:
        for b in self.backends:
            result = await b.narrate(anomaly)
            if result is not None:
                return result
        return None


def build_runtime_narrator() -> LLMNarrator:
    """
    Factory del narrador de RUNTIME: TemplateNarrator → MockNarrator.

    Sin LLM en vivo. Determinista y de latencia cero. Si el JSON de
    plantillas no carga, queda solo MockNarrator.
    """
    from .template_backend import TemplateNarrator

    backends: List[LLMNarrator] = []
    try:
        backends.append(TemplateNarrator())
    except Exception as ex:  # JSON ausente o corrupto
        log.warning("TemplateNarrator no disponible (%s); usando MockNarrator", ex)
    backends.append(MockNarrator())
    return FallbackNarrator(backends)
