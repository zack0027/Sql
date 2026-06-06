"""Interfaz abstracta de narrador (v2, §5).

Strategy pattern: cualquier backend (plantilla determinista, Ollama offline,
mock) implementa `narrate()` y se puede inyectar sin tocar el resto del
código. La interfaz se conserva de la v1; lo que cambia es que el backend
de runtime ya no invoca un LLM en vivo (ver TemplateNarrator).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..models import AnomalyEvent, NarrationResult


class LLMNarrator(ABC):
    """Contrato que todo backend de narración debe satisfacer."""

    @abstractmethod
    async def narrate(self, anomaly: AnomalyEvent) -> Optional[NarrationResult]:
        """
        Produce una narración para la anomalía dada.

        Devuelve None si el backend no está disponible o falló; el
        orquestador decide el fallback (típicamente Mock).
        """

    @abstractmethod
    async def is_available(self) -> bool:
        """Health check; usado para elegir backend al arrancar."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Etiqueta para NarrationResult.model. Ej: 'template-v1', 'llama3.2'."""
