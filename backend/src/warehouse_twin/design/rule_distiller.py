"""Destilación de reglas asistida por LLM (v2, §6.1).

Bucle de refinamiento ligero (human-in-the-loop):
  1. corre el detector sobre el simulador,
  2. recoge los falsos negativos (anomalías reales no capturadas),
  3. pide a Ollama una regla en lenguaje natural que los habría atrapado,
  4. revisión humana (este script solo PROPONE; no auto-aplica),
  5. la regla aprobada se añade a la lista de reglas del runtime.

Es el 'semantic gradient' de Zhang y Jain (Amazon) adaptado a escala de
portafolio. NO corre en runtime: produce un artefacto para revisión.

Uso:
    python -m warehouse_twin.design.rule_distiller --n 3000 --out distilled_rules.md
"""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from typing import List

from ..detection import AnomalyDetector, RuleBasedDetector
from ..models import Movement
from ..simulation import AnomalyInjector, LabeledMovement


def collect_false_negatives(
    detector: AnomalyDetector, n: int, anomaly_ratio: float, seed: int
) -> List[LabeledMovement]:
    """Devuelve los movimientos anómalos que el detector NO atrapó."""
    injector = AnomalyInjector(seed=seed)
    misses: List[LabeledMovement] = []
    for i in range(n):
        if injector.rng.random() < anomaly_ratio:
            labeled = injector.generate_anomaly_labeled()
        else:
            labeled = injector.generate_normal_labeled()

        truth = {t.value for t in labeled.labels}
        predicted = {a.type.value for a in detector.detect(labeled.movement)}
        if truth - predicted:  # algo real no fue detectado
            misses.append(labeled)
        if i % 50 == 0:
            injector.advance_drift(0.5)
    return misses


def _summarize(misses: List[LabeledMovement]) -> dict:
    by_type: Counter = Counter()
    for lm in misses:
        for label in lm.labels:
            by_type[label.value] += 1
    return dict(by_type)


async def propose_rule_with_ollama(misses: List[LabeledMovement]) -> str:
    """Pide a Ollama una regla que cubra los falsos negativos. Fallback si no hay Ollama."""
    from ..narration.ollama_narrator import OllamaNarrator  # reutiliza cliente HTTP
    import httpx

    examples = [
        {
            "movement_type": lm.movement.movement_type.value,
            "quantity": lm.movement.quantity,
            "duration_s": lm.movement.duration_s,
            "rack_id": lm.movement.rack_id,
            "missed_labels": [t.value for t in lm.labels],
        }
        for lm in misses[:15]
    ]
    narrator = OllamaNarrator()
    if not await narrator.is_available():
        return (
            "[Ollama no disponible] Propuesta heurística manual: revisar umbrales "
            "de DurationOutlierRule y añadir una regla contextual sensible a la deriva."
        )

    prompt = (
        "Eres ingeniero de WMS. Aquí hay anomalías que un detector por reglas NO "
        "atrapó (falsos negativos). Propón UNA regla nueva, concisa y determinista, "
        "en pseudocódigo Python sobre un objeto Movement(movement_type, quantity, "
        "duration_s, rack_id, timestamp), que los habría capturado sin generar "
        "falsos positivos en operación normal.\n\n"
        f"Falsos negativos:\n{json.dumps(examples, ensure_ascii=False, indent=2)}\n\n"
        "Responde solo con la regla."
    )
    try:
        async with httpx.AsyncClient(timeout=narrator.timeout_sec) as client:
            r = await client.post(
                f"{narrator.url}/api/generate",
                json={"model": narrator.model, "prompt": prompt, "stream": False},
            )
            r.raise_for_status()
            return r.json().get("response", "").strip()
    except Exception as ex:
        return f"[Error consultando Ollama: {ex}]"


def main() -> None:
    parser = argparse.ArgumentParser(description="Destila reglas desde falsos negativos.")
    parser.add_argument("--n", type=int, default=3000)
    parser.add_argument("--ratio", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=str, default="distilled_rules.md")
    args = parser.parse_args()

    detector = RuleBasedDetector()
    misses = collect_false_negatives(detector, args.n, args.ratio, args.seed)
    summary = _summarize(misses)
    proposal = asyncio.run(propose_rule_with_ollama(misses))

    report = (
        "# Destilación de reglas — propuesta (requiere revisión humana)\n\n"
        f"Falsos negativos recolectados: **{len(misses)}** sobre {args.n} muestras.\n\n"
        f"Distribución por tipo:\n\n```json\n{json.dumps(summary, indent=2)}\n```\n\n"
        "## Regla propuesta por el LLM (offline)\n\n"
        f"{proposal}\n\n"
        "> Esta propuesta NO se aplica automáticamente. Revísala y, si procede, "
        "añádela a `detection/rule_engine.py:default_rules()`.\n"
    )
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(report)
    print(report)
    print(f"\nPropuesta escrita en {args.out}")


if __name__ == "__main__":
    main()
