"""Tests del módulo de detección."""
from __future__ import annotations

from datetime import datetime

import pytest

from warehouse_twin.detection import AnomalyDetector, RuleEngine
from warehouse_twin.models import Movement, Severity


def make_movement(**overrides) -> Movement:
    defaults = {
        "movement_id": "MV-TEST",
        "timestamp": datetime(2026, 5, 17, 14, 30, 0),
        "movement_type": "PICK",
        "sku": "MX-0001",
        "location": "A-001",
        "user_id": "USR_001",
        "quantity": 10,
        "duration_sec": 60,
    }
    defaults.update(overrides)
    return Movement(**defaults)


def test_normal_movement_is_not_anomaly():
    detector = AnomalyDetector()
    anomaly = detector.detect(make_movement())
    assert anomaly.is_anomaly is False
    assert anomaly.severity is Severity.NORMAL


def test_negative_quantity_triggers_critical():
    detector = AnomalyDetector()
    movement = make_movement(movement_type="INSPECTION", quantity=-3, duration_sec=4)
    anomaly = detector.detect(movement)
    assert anomaly.is_anomaly
    assert anomaly.severity is Severity.CRITICAL
    assert "cantidad_negativa" in anomaly.rule_reasons
    assert "duracion_minima" in anomaly.rule_reasons


def test_excessive_duration_triggers_medium_or_high():
    detector = AnomalyDetector()
    movement = make_movement(duration_sec=400)
    anomaly = detector.detect(movement)
    assert anomaly.is_anomaly
    assert anomaly.severity is not Severity.NORMAL


def test_websocket_payload_keys():
    detector = AnomalyDetector()
    movement = make_movement(movement_type="INSPECTION", quantity=-3, duration_sec=4)
    anomaly = detector.detect(movement)
    payload = anomaly.to_websocket_payload()

    expected = {
        "type", "movement_id", "timestamp", "movement_type", "sku",
        "location", "user_id", "quantity", "duration_sec", "severity",
        "is_anomaly", "rule_reasons",
    }
    assert expected.issubset(payload.keys())
    assert payload["type"] == "alert"
