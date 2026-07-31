"""Name normalisation and identity keys.

Deduplication is a policy decision, not a database detail. It lives here so it
can be versioned and tested. The database only enforces
``UNIQUE(project_id, identity_key)``.

Two rules govern this module:

1. **The original spelling is never lost.** ``normalized_name`` exists for
   matching; every piece of evidence keeps the text exactly as it appeared in
   the source file.
2. **Ambiguity never merges.** ``UC_INSP_ENT`` found without a schema does not
   become ``WMS.UC_INSP_ENT``. Absent information keeps entities apart rather
   than collapsing them on a guess.
"""

from __future__ import annotations

import re

from .types import EntityType, RelationType

# Oracle folds unquoted identifiers to upper case, so `uc_insp_ent`,
# `UC_INSP_ENT` and `"UC_INSP_ENT"` denote the same object. Languages in the
# second group are case sensitive and must not be folded.
_CASE_INSENSITIVE_TYPES: frozenset[EntityType] = frozenset(
    {
        EntityType.ORACLE_TABLE,
        EntityType.ORACLE_VIEW,
        EntityType.ORACLE_COLUMN,
        EntityType.ORACLE_SEQUENCE,
        EntityType.ORACLE_PROCEDURE,
        EntityType.ORACLE_FUNCTION,
        EntityType.ORACLE_PACKAGE,
        EntityType.APEX_APPLICATION,
        EntityType.APEX_PAGE,
        EntityType.APEX_ITEM,
        EntityType.APEX_REGION,
        EntityType.APEX_PROCESS,
        EntityType.APEX_VALIDATION,
        EntityType.APEX_BUTTON,
        EntityType.MOCA_COMMAND,
        EntityType.MOCA_VARIABLE,
    }
)

_WHITESPACE = re.compile(r"\s+")
_QUOTED = re.compile(r'^"(.*)"$', re.DOTALL)


def strip_identifier_quotes(name: str) -> str:
    """Remove one layer of Oracle double quotes, if present."""
    match = _QUOTED.match(name.strip())
    return match.group(1) if match else name.strip()


def normalize_name(name: str, entity_type: EntityType) -> str:
    """Return the matching form of ``name`` for the given entity type.

    >>> normalize_name('"uc_insp_ent"', EntityType.ORACLE_TABLE)
    'UC_INSP_ENT'
    >>> normalize_name("getRows", EntityType.JAVASCRIPT_FUNCTION)
    'getRows'
    """
    cleaned = _WHITESPACE.sub(" ", strip_identifier_quotes(name)).strip()
    if entity_type in _CASE_INSENSITIVE_TYPES:
        return cleaned.upper()
    return cleaned


def normalize_relative_path(path: str) -> str:
    """Normalise a project-relative path to forward slashes without a leading dot.

    File identity must not change when the same project is scanned on Windows
    and on Linux.
    """
    unified = path.replace("\\", "/").strip()
    while unified.startswith("./"):
        unified = unified[2:]
    return unified.strip("/")


def entity_identity_key(
    entity_type: EntityType,
    normalized_name: str,
    *,
    schema: str | None = None,
    container: str | None = None,
) -> str:
    """Build the deduplication key for an entity.

    ``schema`` is the Oracle schema when it is *known*; ``container`` scopes
    entities that only exist inside something else — a column inside a table, a
    Jasper field inside its report, a JavaScript function inside its file.

    An empty component means "unknown", and unknown never matches known. That is
    what keeps a bare ``UC_INSP_ENT`` from being merged into ``WMS.UC_INSP_ENT``.
    """
    parts = [
        entity_type.value,
        (schema or "").strip(),
        (container or "").strip(),
        normalized_name,
    ]
    return "|".join(parts)


def relationship_identity_key(
    source_entity_id: str,
    relation_type: RelationType,
    target_entity_id: str,
    source_file_id: str | None,
) -> str:
    """Build the deduplication key for a relationship.

    A relationship is identified by *what it claims* and *where it was found*,
    not by the exact line. The same claim appearing twice in one file is one
    relationship carrying two pieces of evidence; the same claim in two files is
    two relationships, because losing one of the files would otherwise silently
    erase knowledge that the other still supports.
    """
    return "|".join(
        [source_entity_id, relation_type.value, target_entity_id, source_file_id or ""]
    )


def annotation_key(
    source_identity_key: str,
    relation_type: RelationType,
    target_identity_key: str,
) -> str:
    """Semantic key for annotating a relationship.

    Deliberately different from :func:`relationship_identity_key`, which embeds
    entity ids and the file that proved the claim. A person rejecting "this APEX
    item maps to that column" is ruling on the claim itself, not on whichever
    file happened to demonstrate it — and not on ids, which are handed out fresh
    when a file changes and its entities are rebuilt.
    """
    return "|".join(
        [source_identity_key, relation_type.value, target_identity_key]
    )


def split_qualified_name(raw: str) -> tuple[str | None, str]:
    """Split ``SCHEMA.OBJECT`` into its parts, tolerating quotes.

    Returns ``(None, name)`` when the name is not qualified. Names with more than
    two components (``SCHEMA.PACKAGE.PROCEDURE``) keep everything but the last
    component as the qualifier.
    """
    text = raw.strip()
    if "." not in text:
        return None, strip_identifier_quotes(text)
    qualifier, _, name = text.rpartition(".")
    return strip_identifier_quotes(qualifier) or None, strip_identifier_quotes(name)
