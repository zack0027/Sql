"""Narrador Ollama (v2, §5.2) — FASE DE DISEÑO (offline), no runtime.

El OllamaNarrator de la v1 no se elimina: se reubica a la fase offline.
Genera las variantes de narración que el template_generator.py guarda en
narration_templates.json. Sigue usando httpx.AsyncClient para no bloquear, y
Ollama local por privacidad.

NO debe usarse en el camino crítico de runtime (latencia/no-determinismo);
el runtime usa TemplateNarrator. Se mantiene aquí implementando LLMNarrator
para poder compararlo en la fase de diseño y en evaluaciones.

FUNDAMENTO: el LLM local generando explicaciones interpretables se alinea con
Yiheng Zhang, Cao, Xu y Shen (LogiCode, IEEE).
"""
from __future__ import annotations

import json
import time
from typing import Optional

import httpx

from ..config import settings
from ..models import AnomalyEvent, NarrationResult
from .base import LLMNarrator

_SYSTEM_PROMPT = """Eres un experto en operaciones de WMS (Warehouse Management System).
Analizas anomalías detectadas en almacenes y produces explicaciones concisas en español.

Reglas estrictas:
1. Responde SIEMPRE en JSON válido, sin markdown ni texto adicional.
2. Claves obligatorias: "text", "likely_cause", "recommended_action".
3. Cada valor: una frase de 1-2 líneas, profesional y accionable.
4. NO inventes datos que no estén en el input.
"""


class OllamaNarrator(LLMNarrator):
    """Cliente HTTP del API de Ollama (/api/generate). Uso offline."""

    def __init__(
        self,
        url: str | None = None,
        model: str | None = None,
        timeout_sec: float | None = None,
    ):
        self.url = url or settings.ollama_url
        self.model = model or settings.ollama_model
        self.timeout_sec = timeout_sec or settings.ollama_timeout_sec

    @property
    def model_name(self) -> str:
        return self.model

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self.url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False

    async def narrate(self, anomaly: AnomalyEvent) -> Optional[NarrationResult]:
        start = time.perf_counter()

        user_input = {
            "anomaly_type": anomaly.type.value,
            "rack_id": anomaly.rack_id,
            "severity": anomaly.severity.value,
            "detail": anomaly.detail,
        }
        prompt = (
            f"{_SYSTEM_PROMPT}\n\n"
            f"Entrada:\n{json.dumps(user_input, ensure_ascii=False)}\n\nRespuesta:"
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                r = await client.post(
                    f"{self.url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.3, "top_p": 0.9},
                    },
                )
                r.raise_for_status()
                parsed = json.loads(r.json().get("response", "").strip())
        except Exception as ex:
            print(f"[OllamaNarrator] narrate failed: {ex}")
            return None

        return NarrationResult(
            anomaly_id=anomaly.id,
            rack_id=anomaly.rack_id,
            text=parsed.get("text", ""),
            likely_cause=parsed.get("likely_cause"),
            recommended_action=parsed.get("recommended_action"),
            model=self.model_name,
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
        )
