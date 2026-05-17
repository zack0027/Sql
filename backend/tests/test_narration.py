"""Tests del narrador."""
from __future__ import annotations

from datetime import datetime

import pytest

from warehouse_twin.detection import AnomalyDetector
from warehouse_twin.models import Movement
from warehouse_twin.narration import MockNarrator


def make_anomaly():
    detector = AnomalyDetector()
    movement = Movement(
        movement_id="MV-T1",
        timestamp=datetime(2026, 5, 17, 14, 30, 0),
        movement_type="INSPECTION",
        sku="MX-0042",
        location="C-018",
        user_id="USR_001",
        quantity=-3,
        duration_sec=4,
    )
    return detector.detect(movement)


@pytest.mark.asyncio
async def test_mock_narrator_always_available():
    narrator = MockNarrator()
    assert await narrator.is_available() is True


@pytest.mark.asyncio
async def test_mock_narrator_produces_narrative():
    narrator = MockNarrator()
    anomaly = make_anomaly()
    narrative = await narrator.generate(anomaly)
    assert narrative is not None
    assert narrative.movement_id == "MV-T1"
    assert narrative.source == "mock"
    assert len(narrative.narrative) > 20
    assert len(narrative.likely_cause) > 20
    assert len(narrative.recommended_action) > 20


@pytest.mark.asyncio
async def test_websocket_payload_keys_match_unity_contract():
    narrator = MockNarrator()
    anomaly = make_anomaly()
    narrative = await narrator.generate(anomaly)
    payload = narrative.to_websocket_payload()

    expected = {
        "type", "movement_id", "location", "narrative", "likely_cause",
        "recommended_action", "source", "model", "latency_sec", "emitted_at",
    }
    assert expected.issubset(payload.keys())
    assert payload["type"] == "narrative"
