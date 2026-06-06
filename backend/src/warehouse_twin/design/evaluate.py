"""Evaluación del detector (v2, §6.3).

Calcula precisión, recall y F1 POR TIPO de anomalía sobre el simulador con
ground truth, y produce metrics_report.md. Con anomaly_rate≈0.15 se reporta
F1 y no accuracy (que se inflaría con los verdaderos negativos).

FUNDAMENTO: el estándar de evaluación —F1 sobre testbeds, no accuracy— lo fija
Xu, Ali y Yue (LATTICE, Simula / U. Oslo). Castellani et al. (Honda RIE)
advierten que aun pocos falsos positivos vuelven inútil el sistema.

Uso:
    python -m warehouse_twin.design.evaluate --n 5000 --out metrics_report.md
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List

from ..detection import AnomalyDetector, RuleBasedDetector
from ..models import AnomalyType
from ..simulation import AnomalyInjector


@dataclass
class Metrics:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def evaluate(
    detector: AnomalyDetector,
    n: int = 5000,
    anomaly_ratio: float = 0.15,
    seed: int = 42,
) -> Dict[str, Metrics]:
    """Corre el detector sobre n movimientos etiquetados y agrega métricas por tipo."""
    injector = AnomalyInjector(seed=seed)
    per_type: Dict[str, Metrics] = defaultdict(Metrics)

    for i in range(n):
        if injector.rng.random() < anomaly_ratio:
            labeled = injector.generate_anomaly_labeled()
        else:
            labeled = injector.generate_normal_labeled()

        truth = {t.value for t in labeled.labels}
        predicted = {a.type.value for a in detector.detect(labeled.movement)}

        for atype in AnomalyType:
            key = atype.value
            in_truth = key in truth
            in_pred = key in predicted
            if in_pred and in_truth:
                per_type[key].tp += 1
            elif in_pred and not in_truth:
                per_type[key].fp += 1
            elif not in_pred and in_truth:
                per_type[key].fn += 1

        # deriva lenta para exponer drift
        if i % 50 == 0:
            injector.advance_drift(0.5)

    return dict(per_type)


def render_report(metrics: Dict[str, Metrics], n: int) -> str:
    lines: List[str] = [
        "# Reporte de métricas — Warehouse Digital Twin",
        "",
        f"Muestras evaluadas: **{n}**. Métrica principal: **F1 por tipo** "
        "(no accuracy, por el desbalance de clases).",
        "",
        "| Tipo de anomalía | Precisión | Recall | F1 | TP | FP | FN |",
        "|---|---|---|---|---|---|---|",
    ]
    macro_f1 = 0.0
    for atype in AnomalyType:
        m = metrics.get(atype.value, Metrics())
        lines.append(
            f"| {atype.value} | {m.precision:.3f} | {m.recall:.3f} | "
            f"{m.f1:.3f} | {m.tp} | {m.fp} | {m.fn} |"
        )
        macro_f1 += m.f1
    macro_f1 /= len(AnomalyType)
    lines += ["", f"**Macro-F1:** {macro_f1:.3f}", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evalúa el detector con F1 por tipo.")
    parser.add_argument("--n", type=int, default=5000)
    parser.add_argument("--ratio", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=str, default="metrics_report.md")
    args = parser.parse_args()

    metrics = evaluate(RuleBasedDetector(), n=args.n, anomaly_ratio=args.ratio, seed=args.seed)
    report = render_report(metrics, args.n)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(report)
    print(report)
    print(f"\nReporte escrito en {args.out}")


if __name__ == "__main__":
    main()
