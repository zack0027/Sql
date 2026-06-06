"""Tests del simulador enriquecido y la evaluación (v2)."""
from __future__ import annotations

from warehouse_twin.design.evaluate import Metrics, evaluate
from warehouse_twin.detection import RuleBasedDetector
from warehouse_twin.models import AnomalyType
from warehouse_twin.simulation import AnomalyInjector


def test_injector_normal_has_no_labels():
    inj = AnomalyInjector(seed=1)
    labeled = inj.generate_normal_labeled()
    assert labeled.labels == []
    assert labeled.movement.duration_s is not None


def test_injector_ground_truth_matches_kind():
    inj = AnomalyInjector(seed=1)
    assert AnomalyType.NEGATIVE_QUANTITY in inj.generate_anomaly_labeled("negative_qty").labels
    assert AnomalyType.UNKNOWN_RACK in inj.generate_anomaly_labeled("unknown_rack").labels
    assert AnomalyType.TRACEABILITY_BROKEN in inj.generate_anomaly_labeled("traceability").labels


def test_drift_increases_baseline_duration():
    inj = AnomalyInjector(seed=2)
    before = inj.generate_normal().duration_s
    inj.advance_drift(100.0)
    after = inj.generate_normal().duration_s
    # Con +100s de deriva el baseline sube de forma perceptible (en promedio).
    assert after > before


def test_evaluate_returns_metrics_per_type():
    metrics = evaluate(RuleBasedDetector(), n=500, seed=42)
    assert all(isinstance(m, Metrics) for m in metrics.values())
    # Las reglas determinísticas deben recuperar las anomalías que ellas definen.
    assert metrics[AnomalyType.NEGATIVE_QUANTITY.value].f1 > 0.9
