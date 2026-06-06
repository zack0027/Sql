"""Narrador por plantilla (v2, §5.1) — backend de RUNTIME.

En runtime el narrador usa plantillas pre-generadas offline por el LLM y
parametrizadas en el momento. Latencia cero, salida determinista, sin riesgo
de alucinación.

FUNDAMENTO: la eliminación del LLM del camino crítico responde a Zhang y Jain
(Amazon) — latencia, no-determinismo, alucinación — y al survey de Xu y Ding
(Northwestern University). Balasubramanian et al. (Univ. of Oulu) respaldan que
un modelo pequeño (o aquí, una plantilla curada) basta para explicar bien.

La selección de variante usa un hash ESTABLE de anomaly.id (zlib.crc32) en
lugar de hash() de Python, que no es determinista entre procesos.
"""
from __future__ import annotations

import json
import zlib
from pathlib import Path
from typing import Optional

from ..models import AnomalyEvent, NarrationResult
from .base import LLMNarrator

_DEFAULT_TEMPLATES = Path(__file__).parent / "narration_templates.json"


class TemplateNarrator(LLMNarrator):
    """Narrador determinista basado en plantillas versionadas."""

    def __init__(self, templates_path: str | Path = _DEFAULT_TEMPLATES):
        self.templates_path = Path(templates_path)
        with open(self.templates_path, encoding="utf-8") as fh:
            raw = json.load(fh)
        # Ignora claves de metadatos (prefijo "_")
        self._tpl: dict[str, list[dict]] = {
            k: v for k, v in raw.items() if not k.startswith("_")
        }

    @property
    def model_name(self) -> str:
        return "template-v1"

    async def is_available(self) -> bool:
        return bool(self._tpl)

    async def narrate(self, anomaly: AnomalyEvent) -> Optional[NarrationResult]:
        variants = self._tpl.get(anomaly.type.value)
        if not variants:
            return None

        # Selección determinista y estable entre procesos.
        idx = zlib.crc32(anomaly.id.encode("utf-8")) % len(variants)
        variant = variants[idx]

        fmt = dict(rack=anomaly.rack_id, detail=anomaly.detail, sev=anomaly.severity.value)
        return NarrationResult(
            anomaly_id=anomaly.id,
            rack_id=anomaly.rack_id,
            text=variant["text"].format(**fmt),
            likely_cause=(variant.get("likely_cause") or "").format(**fmt) or None,
            recommended_action=(variant.get("recommended_action") or "").format(**fmt) or None,
            model=self.model_name,
            latency_ms=0.0,
        )
