"""Generación de plantillas de narración (v2, §6.2).

Ollama genera N variantes de explicación por tipo de anomalía con un prompt
como 'escribe N variantes técnicas breves para una anomalía de tipo X'. Las
variantes quedan en narration_templates.json, versionado en git y consumido
por el TemplateNarrator en runtime.

Si Ollama no está disponible, conserva el JSON existente (no lo sobrescribe
con basura) y avisa.

Uso:
    python -m warehouse_twin.design.template_generator --variants 3
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import httpx

from ..models import AnomalyType
from ..narration.ollama_narrator import OllamaNarrator

_TEMPLATES_PATH = (
    Path(__file__).resolve().parent.parent / "narration" / "narration_templates.json"
)

_PROMPT = """Eres ingeniero de operaciones de WMS. Genera {k} variantes BREVES (1-2
frases) en español para explicar una anomalía de tipo {atype} en un almacén.
Cada variante es un objeto JSON con las claves: "text", "likely_cause",
"recommended_action". Usa los placeholders {{rack}}, {{detail}} y {{sev}} donde
corresponda. Responde SOLO con un array JSON de {k} objetos.
"""


async def generate_for_type(narrator: OllamaNarrator, atype: AnomalyType, k: int) -> list | None:
    prompt = _PROMPT.format(k=k, atype=atype.value)
    try:
        async with httpx.AsyncClient(timeout=narrator.timeout_sec) as client:
            r = await client.post(
                f"{narrator.url}/api/generate",
                json={
                    "model": narrator.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
            )
            r.raise_for_status()
            parsed = json.loads(r.json().get("response", "").strip())
            # Ollama puede devolver {"variants": [...]} o directamente [...]
            if isinstance(parsed, dict):
                for v in parsed.values():
                    if isinstance(v, list):
                        return v
                return None
            return parsed if isinstance(parsed, list) else None
    except Exception as ex:
        print(f"[template_generator] {atype.value} falló: {ex}")
        return None


async def run(k: int) -> None:
    narrator = OllamaNarrator()
    if not await narrator.is_available():
        print(
            "[template_generator] Ollama no disponible. Se conserva el JSON existente "
            "(no se sobrescribe). Inicia Ollama y reintenta para regenerar."
        )
        return

    with open(_TEMPLATES_PATH, encoding="utf-8") as fh:
        current = json.load(fh)

    for atype in AnomalyType:
        variants = await generate_for_type(narrator, atype, k)
        if variants:
            current[atype.value] = variants
            print(f"[template_generator] {atype.value}: {len(variants)} variantes")
        else:
            print(f"[template_generator] {atype.value}: sin cambios (fallo o vacío)")

    current.setdefault("_meta", {})["generated_by"] = (
        f"design/template_generator.py (Ollama {narrator.model}, offline)"
    )
    with open(_TEMPLATES_PATH, "w", encoding="utf-8") as fh:
        json.dump(current, fh, ensure_ascii=False, indent=2)
    print(f"[template_generator] Escrito {_TEMPLATES_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera plantillas de narración con Ollama.")
    parser.add_argument("--variants", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(run(args.variants))


if __name__ == "__main__":
    main()
