"""Tests del módulo de detección (v2)."""
from __future__ import annotations

from datetime import datetime

from warehouse_twin.detection import HybridDetector, RuleBasedDetector
from warehouse_twin.models import AnomalyType, Movement, MovementType, Severity


def make_movement(**overrides) -> Movement:
    defaults = dict(
        id="MV-TEST",
        rack_id="A-001",
        movement_type=MovementType.PICK,
        quantity=10,
        duration_s=60.0,
        timestamp=datetime(2026, 5, 17, 14, 30, 0),
    )
    defaults.update(overrides)
    return Movement(**defaults)


def test_normal_movement_has_no_anomalies():
    detector = RuleBasedDetector()
    assert detector.detect(make_movement()) == []


def test_negative_quantity_is_high():
    detector = RuleBasedDetector()
    events = detector.detect(make_movement(movement_type=MovementType.INSPECTION, quantity=-3))
    types = {e.type for e in events}
    assert AnomalyType.NEGATIVE_QUANTITY in types
    neg = next(e for e in events if e.type is AnomalyType.NEGATIVE_QUANTITY)
    assert neg.severity is Severity.HIGH


def test_negative_quantity_allowed_in_adjustment():
    detector = RuleBasedDetector()
    events = detector.detect(make_movement(movement_type=MovementType.ADJUSTMENT, quantity=-3))
    assert all(e.type is not AnomalyType.NEGATIVE_QUANTITY for e in events)


def test_duration_outlier_long():
    detector = RuleBasedDetector()
    events = detector.detect(make_movement(duration_s=400))
    assert any(e.type is AnomalyType.DURATION_OUTLIER for e in events)


def test_duration_outlier_short_inspection():
    detector = RuleBasedDetector()
    events = detector.detect(make_movement(movement_type=MovementType.INSPECTION, duration_s=4))
    assert any(e.type is AnomalyType.DURATION_OUTLIER for e in events)


def test_traceability_broken():
    detector = RuleBasedDetector()
    events = detector.detect(make_movement(movement_type=MovementType.TRACEABILITY, quantity=0))
    assert any(e.type is AnomalyType.TRACEABILITY_BROKEN for e in events)


def test_unknown_rack():
    detector = RuleBasedDetector()
    events = detector.detect(make_movement(rack_id="Z-999"))
    assert any(e.type is AnomalyType.UNKNOWN_RACK for e in events)


def test_known_rack_not_flagged():
    detector = RuleBasedDetector()
    events = detector.detect(make_movement(rack_id="F-018"))
    assert all(e.type is not AnomalyType.UNKNOWN_RACK for e in events)


def test_websocket_payload_keys():
    detector = RuleBasedDetector()
    event = detector.detect(make_movement(rack_id="Z-999"))[0]
    payload = event.to_websocket_payload()
    expected = {
        "type", "id", "movement_id", "rack_id", "anomaly_type",
        "severity", "detail", "detector", "timestamp",
    }
    assert expected.issubset(payload.keys())
    assert payload["type"] == "anomaly"


def test_hybrid_deduplicates():
    # Dos detectores por reglas idénticos no deben duplicar la misma anomalía.
    hybrid = HybridDetector([RuleBasedDetector(), RuleBasedDetector()])
    events = hybrid.detect(make_movement(rack_id="Z-999"))
    unknowns = [e for e in events if e.type is AnomalyType.UNKNOWN_RACK]
    assert len(unknowns) == 1
