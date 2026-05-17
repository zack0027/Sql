"""Módulo de narración LLM."""
from .base import LLMNarrator
from .fallback_narrator import FallbackNarrator, build_default_narrator
from .mock_narrator import MockNarrator
from .ollama_narrator import OllamaNarrator

__all__ = [
    "LLMNarrator",
    "MockNarrator",
    "OllamaNarrator",
    "FallbackNarrator",
    "build_default_narrator",
]
