"""Módulo de narración (v2: TemplateNarrator runtime + Ollama offline)."""
from .base import LLMNarrator
from .fallback_narrator import FallbackNarrator, build_runtime_narrator
from .mock_narrator import MockNarrator
from .ollama_narrator import OllamaNarrator
from .template_backend import TemplateNarrator

__all__ = [
    "LLMNarrator",
    "TemplateNarrator",
    "MockNarrator",
    "OllamaNarrator",
    "FallbackNarrator",
    "build_runtime_narrator",
]
