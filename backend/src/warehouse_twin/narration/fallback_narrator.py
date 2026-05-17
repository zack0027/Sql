"""
Composite narrator: intenta una cadena de backends en orden, devuelve la
primera narrativa exitosa.

Esto es lo que el orquestador inyecta en producción. Permite que la demo
funcione siempre: con Ollama si está disponible, con templates si no.
"""
from __future__ import annotations

from typing import List, Optional

from ..models import Anomaly, Narrative
from .base import LLMNarrator
from .mock_narrator import MockNarrator


class FallbackNarrator(LLMNarrator):
    """
    Cadena de narradores. Intenta cada uno en orden.

    Patrón: Chain of Responsibility con fallback automático.
    Si un backend falla o devuelve None, sigue con el siguiente.
    El último siempre debería ser MockNarrator (garantiza no-null).
    """

    def __init__(self, backends: List[LLMNarrator]):
        if not backends:
            raise ValueError("FallbackNarrator necesita al menos un backend")
        self.backends = backends

    @property
    def source_name(self) -> str:
        return "fallback-chain"

    @property
    def model_name(self) -> str:
        return ",".join(b.model_name for b in self.backends)

    async def is_available(self) -> bool:
        # Disponible si cualquiera del chain lo está
        for b in self.backends:
            if await b.is_available():
                return True
        return False

    async def generate(self, anomaly: Anomaly) -> Optional[Narrative]:
        for b in self.backends:
            result = await b.generate(anomaly)
            if result is not None:
                return result
        return None  # solo si TODOS fallaron (no debería pasar con MockNarrator al final)


def build_default_narrator() -> LLMNarrator:
    """
    Factory que arma la cadena estándar: Ollama → Mock.

    Si Ollama está corriendo en localhost, se usa. Si no, automáticamente
    se cae a templates. Es transparente para el resto del sistema.
    """
    from .ollama_narrator import OllamaNarrator

    return FallbackNarrator([OllamaNarrator(), MockNarrator()])
