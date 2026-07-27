"""Confidence bands.

Every fact HANA records carries a number in ``[0, 1]``. The bands below are the
shared vocabulary between analyzers, the query layer and the UI. An analyzer that
cannot justify its number should use :data:`MENTION` and say so.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import VerificationStatus

#: Proven by direct syntax. ``INSERT INTO UC_INSP_ENT`` writes ``UC_INSP_ENT``.
CONFIRMED = 1.0

#: A convention that holds in practice. ``P117_NUMCTL`` belongs to APEX page 117.
STRONG_INFERENCE = 0.90

#: A plausible reading of the source that a human should still check.
PROBABLE_INFERENCE = 0.65

#: A bare token match, e.g. a table name appearing inside a comment.
MENTION = 0.30


@dataclass(frozen=True)
class ConfidenceBand:
    name: str
    lower: float
    upper: float
    label: str


BANDS: tuple[ConfidenceBand, ...] = (
    ConfidenceBand("confirmed", 1.0, 1.0, "Confirmado por sintaxis directa"),
    ConfidenceBand("strong", 0.80, 0.999999, "Inferencia fuerte"),
    ConfidenceBand("probable", 0.50, 0.799999, "Inferencia probable"),
    ConfidenceBand("low", 0.0, 0.499999, "Baja confianza"),
)


def band_of(confidence: float) -> ConfidenceBand:
    """Return the band a confidence value falls into."""
    value = clamp(confidence)
    for band in BANDS:
        if band.lower <= value <= band.upper:
            return band
    return BANDS[-1]  # pragma: no cover - clamp makes this unreachable


def clamp(confidence: float) -> float:
    """Force a confidence value into ``[0, 1]``."""
    return max(0.0, min(1.0, float(confidence)))


def default_status_for(confidence: float) -> VerificationStatus:
    """Map a confidence value to its default verification status.

    Analyzers may override this — a hand-written rule can be certain about
    something it still marks as inferred — but they must never mark something
    ``confirmed`` below 1.0.
    """
    return (
        VerificationStatus.CONFIRMED
        if clamp(confidence) >= CONFIRMED
        else VerificationStatus.INFERRED
    )
