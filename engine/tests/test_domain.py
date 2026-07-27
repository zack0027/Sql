"""Domain rules: identifiers, normalisation, deduplication keys, confidence."""

from __future__ import annotations

import pytest

from hana_engine.domain.analysis import (
    AnalysisContext,
    AnalysisResult,
    Analyzer,
    AnalyzerRegistry,
    EntityDraft,
    SourceSpan,
)
from hana_engine.domain.confidence import (
    CONFIRMED,
    MENTION,
    STRONG_INFERENCE,
    band_of,
    clamp,
    default_status_for,
)
from hana_engine.domain.ids import ULID_LENGTH, is_ulid, new_ulid, timestamp_of
from hana_engine.domain.naming import (
    entity_identity_key,
    normalize_name,
    normalize_relative_path,
    relationship_identity_key,
    split_qualified_name,
)
from hana_engine.domain.types import EntityType, RelationType, VerificationStatus


class TestUlid:
    def test_has_fixed_length_and_alphabet(self):
        value = new_ulid()
        assert len(value) == ULID_LENGTH
        assert is_ulid(value)

    def test_is_unique(self):
        assert len({new_ulid() for _ in range(2000)}) == 2000

    def test_sorts_by_creation_time(self):
        early = new_ulid(timestamp_ms=1_600_000_000_000)
        late = new_ulid(timestamp_ms=1_700_000_000_000)
        assert early < late

    def test_round_trips_its_timestamp(self):
        assert timestamp_of(new_ulid(timestamp_ms=1_650_000_000_123)) == 1_650_000_000_123

    def test_rejects_non_ulids(self):
        assert not is_ulid("nope")
        assert not is_ulid("I" * ULID_LENGTH)  # 'I' is not in Crockford base32


class TestNormalisation:
    @pytest.mark.parametrize(
        "raw", ["uc_insp_ent", "UC_INSP_ENT", '"UC_INSP_ENT"', "  Uc_Insp_Ent  "]
    )
    def test_oracle_names_fold_to_one_form(self, raw):
        assert normalize_name(raw, EntityType.ORACLE_TABLE) == "UC_INSP_ENT"

    def test_case_sensitive_languages_are_not_folded(self):
        assert (
            normalize_name("getRows", EntityType.JAVASCRIPT_FUNCTION) == "getRows"
        )
        assert normalize_name("netwgt", EntityType.JASPER_FIELD) == "netwgt"

    def test_paths_normalise_across_platforms(self):
        assert normalize_relative_path("sql\\guardar.sql") == "sql/guardar.sql"
        assert normalize_relative_path("./sql/guardar.sql") == "sql/guardar.sql"
        assert normalize_relative_path("/sql/guardar.sql/") == "sql/guardar.sql"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("UC_INSP_ENT", (None, "UC_INSP_ENT")),
            ("WMS.UC_INSP_ENT", ("WMS", "UC_INSP_ENT")),
            ('"WMS"."UC_INSP_ENT"', ("WMS", "UC_INSP_ENT")),
            ("WMS.PKG_INSP.REGISTRAR", ("WMS.PKG_INSP", "REGISTRAR")),
        ],
    )
    def test_qualified_names_split(self, raw, expected):
        assert split_qualified_name(raw) == expected


class TestIdentityKeys:
    def test_same_table_different_spellings_share_a_key(self):
        a = entity_identity_key(
            EntityType.ORACLE_TABLE, normalize_name("uc_insp_ent", EntityType.ORACLE_TABLE)
        )
        b = entity_identity_key(
            EntityType.ORACLE_TABLE,
            normalize_name('"UC_INSP_ENT"', EntityType.ORACLE_TABLE),
        )
        assert a == b

    def test_unknown_schema_does_not_merge_into_known_schema(self):
        """The ambiguity rule: absent information keeps entities apart."""
        bare = entity_identity_key(EntityType.ORACLE_TABLE, "UC_INSP_ENT")
        qualified = entity_identity_key(
            EntityType.ORACLE_TABLE, "UC_INSP_ENT", schema="WMS"
        )
        assert bare != qualified

    def test_different_types_never_collide(self):
        table = entity_identity_key(EntityType.ORACLE_TABLE, "NETWGT")
        column = entity_identity_key(EntityType.ORACLE_COLUMN, "NETWGT")
        assert table != column

    def test_container_scopes_columns_to_their_table(self):
        one = entity_identity_key(
            EntityType.ORACLE_COLUMN, "NETWGT", container="UC_INSP_ENT"
        )
        other = entity_identity_key(
            EntityType.ORACLE_COLUMN, "NETWGT", container="PRTMST"
        )
        assert one != other

    def test_relationship_keys_include_the_proving_file(self):
        in_file_a = relationship_identity_key(
            "E1", RelationType.QUERY_READS_TABLE, "E2", "FILE_A"
        )
        in_file_b = relationship_identity_key(
            "E1", RelationType.QUERY_READS_TABLE, "E2", "FILE_B"
        )
        assert in_file_a != in_file_b


class TestConfidence:
    def test_bands(self):
        assert band_of(CONFIRMED).name == "confirmed"
        assert band_of(STRONG_INFERENCE).name == "strong"
        assert band_of(0.65).name == "probable"
        assert band_of(MENTION).name == "low"

    def test_clamping(self):
        assert clamp(2.0) == 1.0
        assert clamp(-3.0) == 0.0

    def test_status_defaults_to_inferred_below_certainty(self):
        assert default_status_for(1.0) is VerificationStatus.CONFIRMED
        assert default_status_for(0.99) is VerificationStatus.INFERRED


class TestDrafts:
    def test_draft_ref_is_its_identity_key(self):
        draft = EntityDraft(EntityType.ORACLE_TABLE, "uc_insp_ent")
        assert draft.normalized_name == "UC_INSP_ENT"
        assert draft.ref == entity_identity_key(EntityType.ORACLE_TABLE, "UC_INSP_ENT")

    def test_confirmed_below_full_confidence_is_rejected(self):
        """Guards the core promise: 'confirmed' always means proven."""
        with pytest.raises(ValueError, match="cannot be 'confirmed'"):
            EntityDraft(
                EntityType.APEX_ITEM,
                "P117_NUMCTL",
                confidence=0.9,
                verification_status=VerificationStatus.CONFIRMED,
            )

    def test_inferred_status_is_assigned_automatically(self):
        draft = EntityDraft(
            EntityType.APEX_PAGE, "117", confidence=STRONG_INFERENCE
        )
        assert draft.verification_status is VerificationStatus.INFERRED

    def test_span_validation(self):
        with pytest.raises(ValueError):
            SourceSpan(0, 5)
        with pytest.raises(ValueError):
            SourceSpan(10, 3)


class TestAnalysisContext:
    def _context(self, content: str) -> AnalysisContext:
        return AnalysisContext(
            project_id="P",
            file_id="F",
            relative_path="sql/x.sql",
            absolute_path="/tmp/sql/x.sql",
            extension=".sql",
            detected_type="sql",
            content=content,
        )

    def test_offsets_map_to_line_numbers(self):
        context = self._context("one\ntwo\nthree\n")
        assert context.line_of_offset(0) == 1
        assert context.line_of_offset(5) == 2
        assert context.line_of_offset(9) == 3

    def test_snippet_returns_the_requested_lines(self):
        context = self._context("alpha\nbeta\ngamma\n")
        assert context.snippet(SourceSpan(2, 3)) == "beta\ngamma"

    def test_snippet_is_truncated_for_storage(self):
        context = self._context("x" * 5000)
        assert len(context.snippet(SourceSpan(1, 1), max_chars=100)) == 100


class TestAnalyzerRegistry:
    class _Sql(Analyzer):
        name = "sql-test"
        supported_extensions = (".sql",)

        def analyze(self, context: AnalysisContext) -> AnalysisResult:
            return AnalysisResult()

    class _Broken(Analyzer):
        name = "broken"
        supported_extensions = (".sql",)

        def can_analyze(self, file_path: str, content: str) -> bool:
            raise RuntimeError("boom")

        def analyze(self, context: AnalysisContext) -> AnalysisResult:
            return AnalysisResult()

    def test_matches_on_extension(self):
        registry = AnalyzerRegistry()
        registry.register(self._Sql())
        assert [a.name for a in registry.for_file("a.sql", "")] == ["sql-test"]
        assert list(registry.for_file("a.jrxml", "")) == []

    def test_duplicate_names_are_rejected(self):
        registry = AnalyzerRegistry()
        registry.register(self._Sql())
        with pytest.raises(ValueError, match="already registered"):
            registry.register(self._Sql())

    def test_a_plugin_that_throws_in_can_analyze_is_skipped(self):
        """One broken plugin must never hide the working ones."""
        registry = AnalyzerRegistry()
        registry.register(self._Broken())
        registry.register(self._Sql())
        assert [a.name for a in registry.for_file("a.sql", "")] == ["sql-test"]
