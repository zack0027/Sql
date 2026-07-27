"""SQLite connection management and migrations.

The knowledge base is a single file. Exactly one process opens it for writing
(the engine); Rust never touches it. WAL mode is enabled so future read-only
consumers — a graph query worker, a background indexer — can read while an
analysis run writes.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..domain.models import utc_now

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

#: Bumped whenever the on-disk layout changes in a way older builds cannot read.
SCHEMA_VERSION_TABLE = "schema_migrations"


class MigrationError(RuntimeError):
    """Raised when the database cannot be brought to the expected schema."""


def connect(db_path: str | Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open the knowledge base, applying the pragmas the engine relies on."""
    path = Path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)

    # ``check_same_thread=False`` is deliberate. The sidecar creates its engine on
    # the main thread but performs every database call on one worker thread (see
    # ``ipc.server``), which Python's default thread-affinity guard would reject
    # even though the access is strictly serialised. CPython's sqlite3 reports
    # ``threadsafety == 3`` (SQLite compiled in serialized mode), so the guard is
    # the only thing in the way. The engine still guarantees a single writer: the
    # IPC queue, not this flag, is what makes it safe.
    if read_only and str(path) != ":memory:":
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    else:
        connection = sqlite3.connect(str(path), check_same_thread=False)

    connection.row_factory = sqlite3.Row
    # Foreign keys are off by default in SQLite; the whole cascade-delete design
    # (reanalysing a file drops its relationships) depends on them being on.
    connection.execute("PRAGMA foreign_keys = ON")
    if not read_only:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA temp_store = MEMORY")
    return connection


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block in one transaction, rolling back on any exception.

    Used per file during analysis so a failure in one file cannot leave half of
    its entities behind.
    """
    try:
        connection.execute("BEGIN")
    except sqlite3.OperationalError:
        # Already inside a transaction — join the outer one.
        yield connection
        return
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()


def _ensure_migration_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_VERSION_TABLE} (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    connection.commit()


def _discover_migrations() -> list[tuple[int, str, Path]]:
    """Return ``(version, name, path)`` for every migration, in order."""
    found: list[tuple[int, str, Path]] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        prefix, _, remainder = path.stem.partition("_")
        try:
            version = int(prefix)
        except ValueError as exc:
            raise MigrationError(
                f"migration filename must start with a number: {path.name}"
            ) from exc
        found.append((version, remainder or path.stem, path))
    found.sort(key=lambda item: item[0])
    return found


def applied_versions(connection: sqlite3.Connection) -> set[int]:
    _ensure_migration_table(connection)
    rows = connection.execute(
        f"SELECT version FROM {SCHEMA_VERSION_TABLE}"
    ).fetchall()
    return {row["version"] for row in rows}


def migrate(connection: sqlite3.Connection) -> list[int]:
    """Apply every pending migration. Returns the versions that ran."""
    _ensure_migration_table(connection)
    already = applied_versions(connection)
    executed: list[int] = []

    for version, name, path in _discover_migrations():
        if version in already:
            continue
        sql = path.read_text(encoding="utf-8")
        try:
            connection.executescript(sql)
        except sqlite3.Error as exc:
            connection.rollback()
            raise MigrationError(f"migration {path.name} failed: {exc}") from exc
        connection.execute(
            f"INSERT INTO {SCHEMA_VERSION_TABLE}(version, name, applied_at) "
            "VALUES (?, ?, ?)",
            (version, name, utc_now()),
        )
        connection.commit()
        executed.append(version)

    return executed


def open_knowledge_base(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) a migrated knowledge base."""
    connection = connect(db_path)
    migrate(connection)
    return connection


def has_fts5(connection: sqlite3.Connection) -> bool:
    """Return True when the SQLite build supports FTS5.

    Checked at startup: without FTS5 the search views must degrade to LIKE
    queries rather than crash.
    """
    row = connection.execute(
        "SELECT 1 FROM pragma_compile_options WHERE compile_options LIKE 'ENABLE_FTS5%'"
    ).fetchone()
    if row is not None:
        return True
    try:
        connection.execute("CREATE VIRTUAL TABLE temp.__fts_probe USING fts5(x)")
    except sqlite3.OperationalError:
        return False
    connection.execute("DROP TABLE temp.__fts_probe")
    return True
