"""Tests del narrador (v2)."""
from __future__ import annotations

import pytest

from warehouse_twin.models import AnomalyEvent, AnomalyType, Severity
from warehouse_twin.narration import MockNarrator, TemplateNarrator
from warehouse_twin.narration.fallback_narrator import build_runtime_narrator


def make_anomaly(atype=AnomalyType.NEGATIVE_QUANTITY) -> AnomalyEvent:
    return AnomalyEvent(
        id="AN-test-001",
        movement_id="MV-T1",
        rack_id="C-018",
        type=atype,
        severity=Severity.HIGH,
        detail="Cantidad negativa (-3) detectada.",
    )


@pytest.mark.asyncio
async def test_template_narrator_available():
    assert await TemplateNarrator().is_available() is True


@pytest.mark.asyncio
async def test_template_narrator_zero_latency_and_deterministic():
    narrator = TemplateNarrator()
    anomaly = make_anomaly()
    first = await narrator.narrate(anomaly)
    second = await narrator.narrate(anomaly)
    assert first is not None
    assert first.latency_ms == 0.0           # runtime determinista, latencia cero
    assert first.model == "template-v1"
    assert first.text == second.text          # mismo id → misma variante
    assert first.anomaly_id == "AN-test-001"


@pytest.mark.asyncio
async def test_template_covers_all_anomaly_types():
    narrator = TemplateNarrator()
    for atype in AnomalyType:
        result = await narrator.narrate(make_anomaly(atype))
        assert result is not None, f"sin plantilla para {atype}"
        assert len(result.text) > 10


@pytest.mark.asyncio
async def test_mock_narrator_always_available():
    assert await MockNarrator().is_available() is True


@pytest.mark.asyncio
async def test_narration_websocket_payload_keys():
    result = await TemplateNarrator().narrate(make_anomaly())
    payload = result.to_websocket_payload()
    expected = {
        "type", "anomaly_id", "rack_id", "text", "likely_cause",
        "recommended_action", "model", "latency_ms", "emitted_at",
    }
    assert expected.issubset(payload.keys())
    assert payload["type"] == "narration"


@pytest.mark.asyncio
async def test_runtime_narrator_is_template_first():
    narrator = build_runtime_narrator()
    result = await narrator.narrate(make_anomaly())
    assert result is not None
    assert result.model == "template-v1"  # template gana sobre mock
