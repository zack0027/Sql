"""Mapping from file extensions to the types HANA knows how to analyse.

The detected type is what the analyzer registry and the UI filter on. It is
deliberately coarser than the extension: ``.sql``, ``.pks`` and ``.pkb`` are all
``plsql`` because the same analyzer reads them.
"""

from __future__ import annotations

from pathlib import PurePosixPath

#: Extension (lower case, with dot) -> detected type.
EXTENSION_TYPES: dict[str, str] = {
    # Oracle / SQL
    ".sql": "sql",
    ".pls": "plsql",
    ".plsql": "plsql",
    ".pks": "plsql",
    ".pkb": "plsql",
    ".prc": "plsql",
    ".fnc": "plsql",
    ".trg": "plsql",
    ".vw": "sql",
    ".spc": "plsql",
    ".bdy": "plsql",
    # Blue Yonder / JDA MOCA
    ".mcmd": "moca",
    ".moca": "moca",
    ".mcom": "moca",
    # JasperReports
    ".jrxml": "jrxml",
    ".jasper": "jasper-compiled",
    # Markup and data
    ".xml": "xml",
    ".xsd": "xml",
    ".xsl": "xml",
    ".xslt": "xml",
    ".json": "json",
    ".jsonc": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".csv": "csv",
    ".properties": "properties",
    ".ini": "properties",
    ".cfg": "properties",
    ".toml": "toml",
    # Code
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".py": "python",
    ".java": "java",
    ".sh": "shell",
    ".bat": "batch",
    ".ps1": "powershell",
    # Documents and text
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".log": "log",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    # Binary assets that can still be relationship targets (report images)
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".bmp": "image",
    ".svg": "image",
    ".ico": "image",
    ".pdf": "document",
    ".xlsx": "spreadsheet",
    ".xls": "spreadsheet",
    ".docx": "document",
    ".zip": "archive",
    ".jar": "archive",
}

#: Types that hold no readable text; the scanner never hashes them as source.
BINARY_TYPES: frozenset[str] = frozenset(
    {"image", "document", "spreadsheet", "archive", "jasper-compiled"}
)

#: Types the MVP's analyzers can read. Everything else is inventoried only.
ANALYZABLE_TYPES: frozenset[str] = frozenset(
    {
        "sql",
        "plsql",
        "moca",
        "jrxml",
        "xml",
        "json",
        "javascript",
        "typescript",
        "python",
        "text",
        "markdown",
        "properties",
        "yaml",
        "html",
        "css",
        "log",
    }
)


def extension_of(path: str) -> str:
    """Return the lower-case extension of a path, including the dot."""
    suffix = PurePosixPath(path.replace("\\", "/")).suffix
    return suffix.lower()


def detect_type(path: str) -> str:
    """Return the detected type for a path, or ``'unknown'``."""
    return EXTENSION_TYPES.get(extension_of(path), "unknown")


def is_binary_type(detected_type: str) -> bool:
    return detected_type in BINARY_TYPES


def is_analyzable(detected_type: str) -> bool:
    return detected_type in ANALYZABLE_TYPES


def guess_project_type(detected_types: dict[str, int]) -> str:
    """Name a project from the mix of file types it contains.

    Used only as a label on the home screen; nothing downstream branches on it.
    """
    if not detected_types:
        return "unknown"

    def count(*types: str) -> int:
        return sum(detected_types.get(t, 0) for t in types)

    oracle = count("sql", "plsql")
    jasper = count("jrxml", "jasper-compiled")
    moca = count("moca")
    code = count("javascript", "typescript", "python")

    ranked = [
        ("blue-yonder-moca", moca),
        ("jasper-reports", jasper),
        ("oracle-apex", oracle),
        ("application-code", code),
    ]
    label, best = max(ranked, key=lambda item: item[1])
    if best == 0:
        return "mixed" if len(detected_types) > 1 else "unknown"
    # A project with both Oracle and Jasper content is most usefully described by
    # whichever dominates, but a meaningful mix deserves the combined label.
    if oracle and jasper and abs(oracle - jasper) < max(oracle, jasper) * 0.5:
        return "oracle-jasper"
    return label
