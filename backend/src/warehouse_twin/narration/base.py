"""
Interfaz abstracta de narrador LLM.

Strategy pattern: cualquier backend (Ollama local, OpenAI, mock) implementa
generate() y se puede inyectar al servidor sin tocar el resto del código.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..models import Anomaly, Narrative


class LLMNarrator(ABC):
    """Contrato que todo backend de narración debe satisfacer."""

    @abstractmethod
    async def generate(self, anomaly: Anomaly) -> Optional[Narrative]:
        """
        Produce una narrativa para la anomalía dada.

        Devuelve None si el backend no está disponible o falló.
        El orquestador decide qué hacer (típicamente: fallback a Mock).
        """

    @abstractmethod
    async def is_available(self) -> bool:
        """Health check; usado para elegir backend al arrancar."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Etiqueta para el campo Narrative.source. Ej: 'ollama', 'mock'."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Etiqueta para el campo Narrative.model. Ej: 'llama-3.2-3b'."""
