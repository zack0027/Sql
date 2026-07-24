"""Secure directory scanning and SHA-256 hashing.

This is the headless scanner: it powers the CLI and the test suite so the engine
can be exercised end to end without compiling Rust. In the packaged desktop app
the same walk is performed by ``crates/jarvis-fs`` and the resulting inventory is
handed to the engine. Both obey :class:`~.policy.ScanPolicy` and produce
:class:`~..domain.models.ScannedFile` records with identical semantics; the
invariants they share are written down in ``docs/SCAN_CONTRACT.md``.

Security posture: the scanner refuses to leave the project root. Every candidate
path is resolved and checked against the root before it is opened, so a symlink,
a junction or a crafted ``..`` component cannot make JARVIS read the user's home
directory.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ..domain.models import ScannedFile
from ..domain.types import SkipReason
from .file_types import detect_type, extension_of, is_binary_type
from .policy import BINARY_SNIFF_BYTES, ScanPolicy

#: Read size for incremental hashing; keeps memory flat on large files.
_HASH_CHUNK_BYTES = 1024 * 1024


class ScanSecurityError(RuntimeError):
    """Raised when a scan is asked to read outside its allowed root."""


class ScanCancelled(RuntimeError):
    """Raised when a cancellation callback asked the walk to stop."""


@dataclass
class ScanReport:
    """The outcome of one walk."""

    root: str
    files: list[ScannedFile] = field(default_factory=list)
    skipped: list[ScannedFile] = field(default_factory=list)
    directories_visited: int = 0
    bytes_hashed: int = 0
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False

    @property
    def total_seen(self) -> int:
        return len(self.files) + len(self.skipped)


def resolve_project_root(root: str | Path) -> Path:
    """Canonicalise the project root, failing if it is not a real directory."""
    path = Path(root).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ScanSecurityError(f"project root does not exist: {root}") from exc
    if not resolved.is_dir():
        raise ScanSecurityError(f"project root is not a directory: {root}")
    return resolved


def is_within(root: Path, candidate: Path) -> bool:
    """Return True when ``candidate`` resolves inside ``root``.

    Uses ``os.path.commonpath`` rather than string prefixes so that
    ``/data/project-secrets`` is not treated as living inside ``/data/project``.
    """
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError):
        return False
    try:
        return os.path.commonpath([str(root), str(resolved)]) == str(root)
    except ValueError:
        # Different drives on Windows.
        return False


def _iso_mtime(stat_result: os.stat_result) -> str:
    return (
        datetime.fromtimestamp(stat_result.st_mtime, tz=UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def hash_file(path: Path) -> tuple[str, int]:
    """Return ``(sha256_hex, bytes_read)`` for a file, read in chunks."""
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def looks_binary(path: Path) -> bool:
    """Detect binary content by sniffing for NUL bytes in the first block."""
    try:
        with path.open("rb") as handle:
            head = handle.read(BINARY_SNIFF_BYTES)
    except OSError:
        return True
    return b"\x00" in head


def _matches_any(name: str, patterns: frozenset[str] | tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def scan_project(
    root: str | Path,
    policy: ScanPolicy | None = None,
    *,
    on_progress: Callable[[int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> ScanReport:
    """Walk ``root``, hashing every readable source file.

    ``on_progress`` receives ``(files_seen, relative_path)`` and must be cheap;
    it is called on the walking thread. ``should_cancel`` is polled between
    files so a long scan can be stopped from the UI.
    """
    resolved_root = resolve_project_root(root)
    active_policy = policy or ScanPolicy()
    report = ScanReport(root=str(resolved_root))

    for scanned in _walk(resolved_root, active_policy, report, should_cancel):
        if scanned.is_skipped:
            report.skipped.append(scanned)
        else:
            report.files.append(scanned)
        if on_progress is not None:
            on_progress(report.total_seen, scanned.relative_path)

    return report


def _walk(
    root: Path,
    policy: ScanPolicy,
    report: ScanReport,
    should_cancel: Callable[[], bool] | None,
) -> Iterator[ScannedFile]:
    ignored_dirs = policy.all_ignored_directories
    stack: list[tuple[Path, int]] = [(root, 0)]

    while stack:
        directory, depth = stack.pop()
        if should_cancel is not None and should_cancel():
            report.cancelled = True
            return

        report.directories_visited += 1
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError as exc:
            report.errors.append(f"{directory}: {exc}")
            continue

        for entry in entries:
            if should_cancel is not None and should_cancel():
                report.cancelled = True
                return

            entry_path = Path(entry.path)
            relative = _relative_path(root, entry_path)

            try:
                is_symlink = entry.is_symlink()
                is_dir = entry.is_dir(follow_symlinks=policy.follow_symlinks)
            except OSError as exc:
                report.errors.append(f"{entry_path}: {exc}")
                continue

            # A symlink is only followed when the policy allows it *and* its
            # target stays inside the project. Otherwise it is recorded as a
            # skipped file so the user can see JARVIS chose not to read it.
            if is_symlink and not policy.follow_symlinks:
                yield _skipped(relative, entry_path, SkipReason.SYMLINK_ESCAPE)
                continue
            if is_symlink and not is_within(root, entry_path):
                yield _skipped(relative, entry_path, SkipReason.SYMLINK_ESCAPE)
                continue

            if is_dir:
                if entry.name in ignored_dirs:
                    continue
                if depth + 1 > policy.max_depth:
                    yield _skipped(relative, entry_path, SkipReason.TOO_DEEP)
                    continue
                stack.append((entry_path, depth + 1))
                continue

            if not entry.is_file(follow_symlinks=policy.follow_symlinks):
                continue  # sockets, FIFOs, devices: not our business
            if _matches_any(entry.name, policy.ignored_files):
                continue

            yield _scan_file(root, entry_path, relative, policy, report)


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - guarded by is_within upstream
        return path.name


def _skipped(relative: str, absolute: Path, reason: SkipReason) -> ScannedFile:
    return ScannedFile(
        relative_path=relative,
        absolute_path=str(absolute),
        extension=extension_of(relative),
        size_bytes=0,
        content_hash=None,
        modified_at=None,
        detected_type=detect_type(relative),
        skip_reason=reason,
    )


def _scan_file(
    root: Path,
    path: Path,
    relative: str,
    policy: ScanPolicy,
    report: ScanReport,
) -> ScannedFile:
    if not is_within(root, path):
        return _skipped(relative, path, SkipReason.SYMLINK_ESCAPE)

    try:
        stat_result = path.stat()
    except OSError as exc:
        report.errors.append(f"{path}: {exc}")
        return _skipped(relative, path, SkipReason.UNREADABLE)

    detected = detect_type(relative)
    common = {
        "relative_path": relative,
        "absolute_path": str(path),
        "extension": extension_of(relative),
        "detected_type": detected,
        "modified_at": _iso_mtime(stat_result),
    }

    if stat_result.st_size > policy.max_file_size_bytes:
        return ScannedFile(
            **common,
            size_bytes=stat_result.st_size,
            content_hash=None,
            skip_reason=SkipReason.TOO_LARGE,
        )

    binary = is_binary_type(detected) or looks_binary(path)
    if binary and not policy.hash_binary_files:
        return ScannedFile(
            **common,
            size_bytes=stat_result.st_size,
            content_hash=None,
            skip_reason=SkipReason.BINARY,
        )

    try:
        content_hash, hashed = hash_file(path)
    except OSError as exc:
        report.errors.append(f"{path}: {exc}")
        return ScannedFile(
            **common,
            size_bytes=stat_result.st_size,
            content_hash=None,
            skip_reason=SkipReason.UNREADABLE,
        )

    report.bytes_hashed += hashed
    # Binary files are hashed (so a changed report image is detected) but marked
    # so no analyzer ever tries to read them as text.
    return ScannedFile(
        **common,
        size_bytes=stat_result.st_size,
        content_hash=content_hash,
        skip_reason=SkipReason.BINARY if binary else None,
    )


def read_text_file(path: str | Path, *, max_bytes: int | None = None) -> str:
    """Read a source file as text, tolerating imperfect encodings.

    Oracle and MOCA exports in the wild are frequently Latin-1 or UTF-8 with a
    BOM. Decoding with ``errors='replace'`` keeps a mis-encoded byte from
    aborting the analysis of an otherwise readable file.
    """
    target = Path(path)
    data = target.read_bytes()
    if max_bytes is not None:
        data = data[:max_bytes]
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
