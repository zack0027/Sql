"""Scan policy — the single definition of what HANA is allowed to read.

Both scanners (the Rust one in ``crates/hana-fs`` and the Python one next
door) implement this policy. It is written down once, here and in
``docs/SCAN_CONTRACT.md``, so the two cannot drift silently.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

#: Directories skipped unless the user removes them from the project settings.
DEFAULT_IGNORED_DIRECTORIES: tuple[str, ...] = (
    ".git",
    "node_modules",
    "target",
    "dist",
    "build",
    ".next",
    ".venv",
    "venv",
    "__pycache__",
    ".idea",
    ".vscode",
    "coverage",
)

#: Filename globs skipped by default.
DEFAULT_IGNORED_FILES: tuple[str, ...] = (
    "*.pyc",
    "*.pyo",
    "*.class",
    "*.o",
    "*.so",
    "*.dll",
    "*.exe",
    "*.lock",
    ".DS_Store",
    "Thumbs.db",
)

#: 5 MiB. Larger source files are inventoried but not hashed or analysed.
DEFAULT_MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024

#: Depth is counted in path components below the project root.
DEFAULT_MAX_DEPTH = 24

#: Bytes read when deciding whether a file is binary.
BINARY_SNIFF_BYTES = 8192


@dataclass(frozen=True)
class ScanPolicy:
    """Limits enforced on every directory walk.

    ``follow_symlinks`` defaults to False. Following a symlink is how a scan
    escapes the folder the user selected, so turning it on is an explicit,
    per-project decision — and even then the resolved target must still fall
    inside the project root.
    """

    ignored_directories: tuple[str, ...] = DEFAULT_IGNORED_DIRECTORIES
    ignored_files: tuple[str, ...] = DEFAULT_IGNORED_FILES
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES
    max_depth: int = DEFAULT_MAX_DEPTH
    follow_symlinks: bool = False
    hash_binary_files: bool = True
    extra_ignored_directories: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        # A policy now arrives from the settings screen, so these are reachable
        # by typing rather than only by a programming mistake. A zero size limit
        # or a zero depth would scan nothing at all and look like an empty
        # project — a wrong answer is worse than a rejected one.
        if self.max_file_size_bytes <= 0:
            raise ValueError("max_file_size_bytes debe ser mayor que cero")
        if self.max_depth <= 0:
            raise ValueError("max_depth debe ser mayor que cero")

    @property
    def all_ignored_directories(self) -> frozenset[str]:
        return frozenset(self.ignored_directories) | frozenset(
            self.extra_ignored_directories
        )

    def with_overrides(self, **changes: Any) -> ScanPolicy:
        return replace(self, **changes)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> ScanPolicy:
        """Build a policy from persisted project settings, ignoring junk keys."""
        if not data:
            return cls()
        return cls(
            ignored_directories=tuple(
                data.get("ignored_directories", DEFAULT_IGNORED_DIRECTORIES)
            ),
            ignored_files=tuple(data.get("ignored_files", DEFAULT_IGNORED_FILES)),
            max_file_size_bytes=int(
                data.get("max_file_size_bytes", DEFAULT_MAX_FILE_SIZE_BYTES)
            ),
            max_depth=int(data.get("max_depth", DEFAULT_MAX_DEPTH)),
            follow_symlinks=bool(data.get("follow_symlinks", False)),
            hash_binary_files=bool(data.get("hash_binary_files", True)),
            extra_ignored_directories=tuple(data.get("extra_ignored_directories", ())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ignored_directories": list(self.ignored_directories),
            "ignored_files": list(self.ignored_files),
            "max_file_size_bytes": self.max_file_size_bytes,
            "max_depth": self.max_depth,
            "follow_symlinks": self.follow_symlinks,
            "hash_binary_files": self.hash_binary_files,
            "extra_ignored_directories": list(self.extra_ignored_directories),
        }
