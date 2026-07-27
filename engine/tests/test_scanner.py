"""Secure scanning, hashing and file typing.

These cases mirror ``crates/hana-fs/src/scanner.rs``; the shared invariants are
listed in ``docs/SCAN_CONTRACT.md``. When one side changes, the other must too.
"""

from __future__ import annotations

import hashlib
import os

import pytest

from hana_engine.domain.types import SkipReason
from hana_engine.indexing.file_types import (
    detect_type,
    extension_of,
    guess_project_type,
    is_analyzable,
    is_binary_type,
)
from hana_engine.indexing.policy import ScanPolicy
from hana_engine.indexing.scanner import (
    ScanSecurityError,
    hash_file,
    is_within,
    read_text_file,
    resolve_project_root,
    scan_project,
)


def _by_path(report) -> dict[str, object]:
    return {item.relative_path: item for item in report.files + report.skipped}


class TestFileTypes:
    @pytest.mark.parametrize(
        "path,expected",
        [
            ("a/b/guardar.sql", "sql"),
            ("pkg_inspeccion.pkb", "plsql"),
            ("Usr-RptInspeccion.jrxml", "jrxml"),
            ("confirmar.mcmd", "moca"),
            ("config.JSON", "json"),
            ("images/checkboxOn.png", "image"),
            ("notes.unknownext", "unknown"),
        ],
    )
    def test_detection(self, path, expected):
        assert detect_type(path) == expected

    def test_extension_is_lowercased(self):
        assert extension_of("REPORT.JRXML") == ".jrxml"

    def test_binary_and_analyzable_classification(self):
        assert is_binary_type("image")
        assert not is_analyzable("image")
        assert is_analyzable("plsql")

    def test_project_type_is_guessed_from_the_file_mix(self):
        assert guess_project_type({"sql": 20, "plsql": 5}) == "oracle-apex"
        assert guess_project_type({"moca": 30, "sql": 2}) == "blue-yonder-moca"
        assert guess_project_type({"sql": 10, "jrxml": 9}) == "oracle-jasper"
        assert guess_project_type({}) == "unknown"


class TestPathSecurity:
    def test_missing_root_is_rejected(self, tmp_path):
        with pytest.raises(ScanSecurityError):
            resolve_project_root(tmp_path / "nope")

    def test_a_file_is_not_a_project_root(self, tmp_path):
        target = tmp_path / "a.sql"
        target.write_text("select 1 from dual;", encoding="utf-8")
        with pytest.raises(ScanSecurityError):
            resolve_project_root(target)

    def test_sibling_prefixes_are_not_inside(self, tmp_path):
        """`/data/project-secrets` must not count as inside `/data/project`."""
        root = tmp_path / "project"
        sibling = tmp_path / "project-secrets"
        root.mkdir()
        sibling.mkdir()
        assert not is_within(root.resolve(), sibling / "creds.txt")

    def test_dotdot_cannot_escape(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
        assert not is_within(root.resolve(), root / ".." / "outside.txt")


class TestScanning:
    def test_finds_the_project_files(self, sample_project):
        report = scan_project(sample_project)
        paths = {item.relative_path for item in report.files}
        assert "sql/guardar_inspeccion.sql" in paths
        assert "reports/Usr-RptInspeccion.jrxml" in paths
        assert "moca/confirmar_inspeccion.mcmd" in paths
        assert "config/apex_inspeccion.json" in paths

    def test_default_ignore_list_is_applied(self, sample_project):
        report = scan_project(sample_project)
        everything = _by_path(report)
        assert not any(path.startswith("node_modules/") for path in everything)
        assert not any(path.startswith(".git/") for path in everything)
        assert not any(path.startswith("build/") for path in everything)

    def test_ignore_list_is_configurable(self, sample_project):
        policy = ScanPolicy(ignored_directories=())
        report = scan_project(sample_project, policy)
        paths = {item.relative_path for item in report.files}
        assert "node_modules/pkg/index.js" in paths

    def test_hashes_match_sha256_of_the_bytes(self, sample_project):
        report = scan_project(sample_project)
        scanned = _by_path(report)["sql/guardar_inspeccion.sql"]
        expected = hashlib.sha256(
            (sample_project / "sql" / "guardar_inspeccion.sql").read_bytes()
        ).hexdigest()
        assert scanned.content_hash == expected

    def test_identical_content_hashes_identically(self, tmp_path):
        root = tmp_path / "p"
        root.mkdir()
        (root / "a.sql").write_text("select 1 from dual;", encoding="utf-8")
        (root / "b.sql").write_text("select 1 from dual;", encoding="utf-8")
        report = scan_project(root)
        hashes = {item.content_hash for item in report.files}
        assert len(hashes) == 1

    def test_relative_paths_use_forward_slashes(self, sample_project):
        report = scan_project(sample_project)
        assert all("\\" not in item.relative_path for item in report.files)

    def test_binary_files_are_hashed_but_flagged(self, sample_project):
        scanned = _by_path(scan_project(sample_project))[
            "reports/images/checkboxOn.png"
        ]
        assert scanned.skip_reason is SkipReason.BINARY
        assert scanned.content_hash is not None  # a changed image must be detectable

    def test_oversized_files_are_inventoried_but_not_hashed(self, tmp_path):
        root = tmp_path / "p"
        root.mkdir()
        (root / "big.sql").write_text("x" * 5000, encoding="utf-8")
        report = scan_project(root, ScanPolicy(max_file_size_bytes=1000))
        scanned = _by_path(report)["big.sql"]
        assert scanned.skip_reason is SkipReason.TOO_LARGE
        assert scanned.content_hash is None
        assert scanned.size_bytes == 5000

    def test_depth_limit_is_enforced(self, tmp_path):
        root = tmp_path / "p"
        deep = root / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "deep.sql").write_text("select 1 from dual;", encoding="utf-8")
        (root / "shallow.sql").write_text("select 1 from dual;", encoding="utf-8")

        report = scan_project(root, ScanPolicy(max_depth=2))
        paths = {item.relative_path for item in report.files}
        assert "shallow.sql" in paths
        assert "a/b/c/d/deep.sql" not in paths

    def test_ignored_file_patterns(self, tmp_path):
        root = tmp_path / "p"
        root.mkdir()
        (root / "keep.sql").write_text("select 1 from dual;", encoding="utf-8")
        (root / "drop.pyc").write_bytes(b"\x00\x01")
        report = scan_project(root)
        assert {item.relative_path for item in report.files} == {"keep.sql"}

    @pytest.mark.skipif(
        os.name == "nt", reason="symlink creation needs elevation on Windows"
    )
    def test_symlinks_are_not_followed_by_default(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.sql").write_text("select * from payroll;", encoding="utf-8")

        root = tmp_path / "project"
        root.mkdir()
        (root / "escape").symlink_to(outside, target_is_directory=True)
        (root / "own.sql").write_text("select 1 from dual;", encoding="utf-8")

        report = scan_project(root)
        assert {item.relative_path for item in report.files} == {"own.sql"}
        skipped = {item.relative_path: item for item in report.skipped}
        assert skipped["escape"].skip_reason is SkipReason.SYMLINK_ESCAPE

    @pytest.mark.skipif(
        os.name == "nt", reason="symlink creation needs elevation on Windows"
    )
    def test_symlinks_that_escape_are_refused_even_when_following_is_enabled(
        self, tmp_path
    ):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.sql").write_text("select * from payroll;", encoding="utf-8")

        root = tmp_path / "project"
        root.mkdir()
        (root / "escape").symlink_to(outside, target_is_directory=True)

        report = scan_project(root, ScanPolicy(follow_symlinks=True))
        assert not any("secret" in item.relative_path for item in report.files)

    @pytest.mark.skipif(
        os.name == "nt",
        reason="Windows ignores POSIX directory modes, so the folder stays readable",
    )
    def test_unreadable_directory_is_reported_without_aborting(self, tmp_path):
        root = tmp_path / "p"
        blocked = root / "locked"
        blocked.mkdir(parents=True)
        (blocked / "inner.sql").write_text("select 1 from dual;", encoding="utf-8")
        (root / "ok.sql").write_text("select 1 from dual;", encoding="utf-8")

        blocked.chmod(0o000)
        try:
            report = scan_project(root)
        finally:
            blocked.chmod(0o755)

        assert "ok.sql" in {item.relative_path for item in report.files}
        # geteuid only exists on POSIX, which the skipif above guarantees.
        if os.geteuid() != 0:  # root can read anything, so nothing would fail
            assert report.errors

    def test_progress_and_cancellation(self, sample_project):
        seen: list[str] = []
        report = scan_project(
            sample_project,
            on_progress=lambda count, path: seen.append(path),
            should_cancel=lambda: len(seen) >= 2,
        )
        assert report.cancelled is True
        assert report.total_seen <= 3


class TestHashingAndReading:
    def test_hash_file_returns_digest_and_size(self, tmp_path):
        target = tmp_path / "a.sql"
        target.write_bytes(b"select 1 from dual;")
        digest, size = hash_file(target)
        assert digest == hashlib.sha256(b"select 1 from dual;").hexdigest()
        assert size == 19

    def test_large_files_hash_in_chunks_without_loading_everything(self, tmp_path):
        target = tmp_path / "big.bin"
        payload = b"hana" * 400_000  # ~2.4 MB, larger than one chunk
        target.write_bytes(payload)
        digest, size = hash_file(target)
        assert digest == hashlib.sha256(payload).hexdigest()
        assert size == len(payload)

    def test_latin1_source_is_read_without_crashing(self, tmp_path):
        """Oracle and MOCA exports are frequently cp1252, not UTF-8."""
        target = tmp_path / "acentos.sql"
        target.write_bytes("-- inspección de tarimas\nselect 1 from dual;".encode("cp1252"))
        text = read_text_file(target)
        assert "inspecci" in text
        assert "select 1 from dual;" in text

    def test_utf8_bom_is_stripped(self, tmp_path):
        target = tmp_path / "bom.sql"
        target.write_bytes(b"\xef\xbb\xbfselect 1 from dual;")
        assert read_text_file(target).startswith("select")
