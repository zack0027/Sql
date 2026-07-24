"""Local language-model providers.

JARVIS works without a model. This module exists so that when one is added it
plugs into a seam that already exists, instead of being threaded through the
codebase after the fact.

The MVP ships :class:`DisabledModelProvider`. Nothing in the engine calls a
provider on a critical path; a model is an optional aid for explaining the graph,
never the source of the graph.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelInfo:
    """A model the provider can serve."""

    id: str
    name: str
    context_window: int = 0
    parameters: str = ""
    quantization: str = ""
    local_path: str | None = None


@dataclass
class ModelRequest:
    """A generation request. Deliberately provider-agnostic."""

    prompt: str
    system: str | None = None
    model_id: str | None = None
    max_tokens: int = 512
    temperature: float = 0.2
    stop: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelResponse:
    """A generation result, or the reason there isn't one."""

    text: str
    model_id: str
    finish_reason: str = "stop"
    tokens_generated: int = 0
    available: bool = True
    error: str | None = None


class LocalModelProvider(ABC):
    """Contract every local backend implements.

    Implementations must run entirely on the user's machine. A provider that
    reaches a remote API does not belong in JARVIS.
    """

    #: Stable identifier shown in settings.
    id: str = "provider"
    #: Human-readable name.
    label: str = "Provider"

    @abstractmethod
    def is_available(self) -> bool:
        """Return True when the backend can serve a request right now."""

    @abstractmethod
    def list_models(self) -> list[ModelInfo]:
        """Return the models this backend can load."""

    @abstractmethod
    def generate(self, request: ModelRequest) -> ModelResponse:
        """Run one generation. Must not raise for an unavailable backend."""


class DisabledModelProvider(LocalModelProvider):
    """The default: no model, and honest about it.

    Returns a well-formed :class:`ModelResponse` with ``available=False`` rather
    than raising, so callers never need a special path for "no model installed".
    """

    id = "disabled"
    label = "Sin modelo local"

    def is_available(self) -> bool:
        return False

    def list_models(self) -> list[ModelInfo]:
        return []

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            text="",
            model_id=request.model_id or "none",
            finish_reason="unavailable",
            available=False,
            error=(
                "No hay un modelo local configurado. JARVIS responde consultas "
                "deterministas contra el grafo sin necesidad de un modelo."
            ),
        )


class EchoModelProvider(LocalModelProvider):
    """A deterministic stand-in used by tests.

    It proves the seam works end to end without pulling in a real runtime.
    """

    id = "echo"
    label = "Echo (pruebas)"

    def is_available(self) -> bool:
        return True

    def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id="echo-1", name="Echo", context_window=2048)]

    def generate(self, request: ModelRequest) -> ModelResponse:
        text = request.prompt.strip()
        return ModelResponse(
            text=text,
            model_id=request.model_id or "echo-1",
            tokens_generated=len(text.split()),
        )


#: Registry of providers by id. Future backends (llama.cpp, Ollama, a bundled
#: GGUF) register here without touching call sites.
PROVIDERS: dict[str, type[LocalModelProvider]] = {
    DisabledModelProvider.id: DisabledModelProvider,
    EchoModelProvider.id: EchoModelProvider,
}


def get_provider(provider_id: str = "disabled") -> LocalModelProvider:
    """Instantiate a provider by id, falling back to the disabled one."""
    return PROVIDERS.get(provider_id, DisabledModelProvider)()
