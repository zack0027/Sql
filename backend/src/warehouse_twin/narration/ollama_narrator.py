"""
Narrador que usa Ollama (LLM local) para generar explicaciones contextuales.

Diseño: el prompt incluye few-shot examples del formato esperado para
que el modelo devuelva JSON estricto. Si Ollama no está disponible o
devuelve algo no parseable, devolvemos None y el orquestador cae a Mock.
"""
from __future__ import annotations

import json
import time
from typing import Optional

import httpx

from ..config import settings
from ..models import Anomaly, Narrative
from .base import LLMNarrator


_SYSTEM_PROMPT = """Eres un experto en operaciones de WMS (Warehouse Management System).
Tu trabajo es analizar anomalías detectadas en almacenes y producir explicaciones
concisas en español para operarios y supervisores.

Reglas estrictas:
1. Responde SIEMPRE en formato JSON válido, sin markdown ni texto adicional.
2. Las 3 claves obligatorias son: "narrative", "likely_cause", "recommended_action".
3. Cada valor debe ser una frase de 1-2 líneas, profesional y accionable.
4. NO inventes datos que no estén en el input.
"""

_FEW_SHOT = """Ejemplo de entrada:
{"movement_type": "INSPECTION", "sku": "MX-0042", "location": "C-018",
 "quantity": -3, "duration_sec": 4, "rule_reasons": "cantidad_negativa, duracion_minima"}

Ejemplo de respuesta:
{"narrative": "Inspección en C-018 sobre el SKU MX-0042 con cantidad negativa y duración inferior al mínimo técnico (4s).",
 "likely_cause": "Cierre prematuro del proceso de inspección o ajuste manual no autorizado.",
 "recommended_action": "Auditar el evento con el supervisor de turno y validar el inventario físico del SKU."}
"""


class OllamaNarrator(LLMNarrator):
    """Cliente HTTP del API de Ollama (/api/generate)."""

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
    def source_name(self) -> str:
        return "ollama"

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

    async def generate(self, anomaly: Anomaly) -> Optional[Narrative]:
        start = time.perf_counter()
        m = anomaly.movement

        user_input = {
            "movement_type": m.movement_type,
            "sku": m.sku,
            "location": m.location,
            "quantity": m.quantity,
            "duration_sec": m.duration_sec,
            "rule_reasons": ", ".join(anomaly.rule_reasons),
            "severity": anomaly.severity.value,
        }
        prompt = (
            f"{_SYSTEM_PROMPT}\n\n{_FEW_SHOT}\n\n"
            f"Entrada:\n{json.dumps(user_input, ensure_ascii=False)}\n\n"
            f"Respuesta:"
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                r = await client.post(
                    f"{self.url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",  # fuerza JSON output (Ollama feature)
                        "options": {"temperature": 0.3, "top_p": 0.9},
                    },
                )
                r.raise_for_status()
                response_text = r.json().get("response", "").strip()
                parsed = json.loads(response_text)
        except Exception as ex:
            # En producción: log al observability stack
            print(f"[OllamaNarrator] generate failed: {ex}")
            return None

        return Narrative(
            movement_id=m.movement_id,
            location=m.location,
            narrative=parsed.get("narrative", ""),
            likely_cause=parsed.get("likely_cause", ""),
            recommended_action=parsed.get("recommended_action", ""),
            source=self.source_name,
            model=self.model_name,
            latency_sec=round(time.perf_counter() - start, 3),
        )
