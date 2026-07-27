"""Guards the Python <-> TypeScript vocabulary from drifting.

``packages/shared-types/src/index.ts`` restates every closed vocabulary the
engine defines. A copy nobody checks becomes wrong; this test parses the
TypeScript and compares it to the enums, so adding an entity type in one language
and forgetting the other fails here instead of in the UI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hana_engine.domain.confidence import (
    CONFIRMED,
    MENTION,
    PROBABLE_INFERENCE,
    STRONG_INFERENCE,
)
from hana_engine.domain.types import (
    AnalysisRunStatus,
    ChangeKind,
    EntityType,
    FileAnalysisStatus,
    ProjectStatus,
    RelationType,
    Severity,
    SkipReason,
    VerificationStatus,
)

SHARED_TYPES = (
    Path(__file__).resolve().parents[2] / "packages" / "shared-types" / "src" / "index.ts"
)


def _typescript_const_values(source: str, name: str) -> set[str]:
    """Extract the string values of an `export const X = {...} as const` block."""
    match = re.search(
        rf"export const {name} = \{{(.*?)\}} as const;", source, re.DOTALL
    )
    if match is None:
        raise AssertionError(f"{name} is not declared in shared-types")
    return set(re.findall(r"'([^']+)'", match.group(1)))


@pytest.fixture(scope="module")
def source() -> str:
    assert SHARED_TYPES.exists(), f"missing {SHARED_TYPES}"
    return SHARED_TYPES.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "name,enum",
    [
        ("EntityType", EntityType),
        ("RelationType", RelationType),
        ("VerificationStatus", VerificationStatus),
        ("FileAnalysisStatus", FileAnalysisStatus),
        ("ChangeKind", ChangeKind),
        ("ProjectStatus", ProjectStatus),
        ("AnalysisRunStatus", AnalysisRunStatus),
        ("Severity", Severity),
        ("SkipReason", SkipReason),
    ],
)
def test_vocabularies_match(source: str, name: str, enum) -> None:
    assert _typescript_const_values(source, name) == {member.value for member in enum}


def test_confidence_constants_match(source: str) -> None:
    values = dict(
        re.findall(r"(\w+): ([0-9.]+),", re.search(
            r"export const Confidence = \{(.*?)\} as const;", source, re.DOTALL
        ).group(1))
    )
    assert float(values["CONFIRMED"]) == CONFIRMED
    assert float(values["STRONG_INFERENCE"]) == STRONG_INFERENCE
    assert float(values["PROBABLE_INFERENCE"]) == PROBABLE_INFERENCE
    assert float(values["MENTION"]) == MENTION


def test_every_entity_type_is_covered() -> None:
    """A spot check that the spec's list is complete, not just self-consistent."""
    required = {
        "OracleTable",
        "ApexItem",
        "ApexPage",
        "JasperReport",
        "JasperField",
        "MocaCommand",
        "MocaVariable",
        "JsonProperty",
        "JavaScriptFunction",
        "PythonFunction",
    }
    assert required <= {member.value for member in EntityType}
