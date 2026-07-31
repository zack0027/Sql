"""Closed vocabularies of the domain.

Every string that the knowledge base stores in a ``*_type`` or ``status`` column
is defined here. The frontend mirrors these values in
``packages/shared-types``; the two lists are kept in sync by
``engine/tests/test_shared_types_sync.py``.
"""

from __future__ import annotations

# Every vocabulary below subclasses StrEnum, so members *are* their string value.
# That is what lets ``json.dumps`` serialise a domain object without a custom
# encoder, and what lets SQLite store ``member.value`` and read it back.
from enum import StrEnum


class EntityType(StrEnum):
    """Kinds of identifiable things HANA can find."""

    PROJECT = "Project"
    FILE = "File"
    DIRECTORY = "Directory"

    ORACLE_TABLE = "OracleTable"
    ORACLE_VIEW = "OracleView"
    ORACLE_COLUMN = "OracleColumn"
    ORACLE_SEQUENCE = "OracleSequence"
    ORACLE_PROCEDURE = "OracleProcedure"
    ORACLE_FUNCTION = "OracleFunction"
    ORACLE_PACKAGE = "OraclePackage"
    SQL_QUERY = "SqlQuery"

    APEX_APPLICATION = "ApexApplication"
    APEX_PAGE = "ApexPage"
    APEX_ITEM = "ApexItem"
    APEX_REGION = "ApexRegion"
    APEX_PROCESS = "ApexProcess"
    APEX_VALIDATION = "ApexValidation"
    APEX_BUTTON = "ApexButton"

    JASPER_REPORT = "JasperReport"
    JASPER_FIELD = "JasperField"
    JASPER_PARAMETER = "JasperParameter"
    JASPER_VARIABLE = "JasperVariable"
    JASPER_SUBREPORT = "JasperSubreport"

    MOCA_COMMAND = "MocaCommand"
    MOCA_VARIABLE = "MocaVariable"

    JSON_PROPERTY = "JsonProperty"
    XML_ELEMENT = "XmlElement"
    JAVASCRIPT_FUNCTION = "JavaScriptFunction"
    PYTHON_FUNCTION = "PythonFunction"

    ERROR = "Error"
    SOLUTION = "Solution"
    UNKNOWN = "UnknownEntity"


class RelationType(StrEnum):
    """Kinds of edges in the knowledge graph."""

    FILE_CONTAINS_ENTITY = "FILE_CONTAINS_ENTITY"
    QUERY_READS_TABLE = "QUERY_READS_TABLE"
    QUERY_WRITES_TABLE = "QUERY_WRITES_TABLE"
    QUERY_USES_COLUMN = "QUERY_USES_COLUMN"
    #: A column belongs to a table. The fact was always known — it is what
    #: ``container`` records — but until it was an edge, nothing could walk from
    #: a column to the reports and pipelines that read its table.
    TABLE_HAS_COLUMN = "TABLE_HAS_COLUMN"
    PROCEDURE_CALLS_PROCEDURE = "PROCEDURE_CALLS_PROCEDURE"
    APEX_PAGE_CONTAINS_ITEM = "APEX_PAGE_CONTAINS_ITEM"
    APEX_ITEM_MAPS_TO_COLUMN = "APEX_ITEM_MAPS_TO_COLUMN"
    APEX_PROCESS_UPDATES_TABLE = "APEX_PROCESS_UPDATES_TABLE"
    REPORT_USES_PARAMETER = "REPORT_USES_PARAMETER"
    REPORT_USES_FIELD = "REPORT_USES_FIELD"
    REPORT_QUERIES_TABLE = "REPORT_QUERIES_TABLE"
    REPORT_REFERENCES_IMAGE = "REPORT_REFERENCES_IMAGE"
    REPORT_INCLUDES_SUBREPORT = "REPORT_INCLUDES_SUBREPORT"
    MOCA_COMMAND_USES_VARIABLE = "MOCA_COMMAND_USES_VARIABLE"
    ENTITY_DEFINED_IN_FILE = "ENTITY_DEFINED_IN_FILE"
    ERROR_AFFECTS_ENTITY = "ERROR_AFFECTS_ENTITY"
    SOLUTION_RESOLVES_ERROR = "SOLUTION_RESOLVES_ERROR"
    ENTITY_DEPENDS_ON_ENTITY = "ENTITY_DEPENDS_ON_ENTITY"
    ENTITY_MENTIONS_ENTITY = "ENTITY_MENTIONS_ENTITY"
    #: Two tables joined in a query. This is not a declared foreign key — HANA
    #: never connects to Oracle — but a join condition is direct syntax stating
    #: that these tables relate on these columns, which is exactly what an
    #: entity-relationship view needs in order to be honest.
    TABLE_JOINS_TABLE = "TABLE_JOINS_TABLE"


class VerificationStatus(StrEnum):
    """How a piece of knowledge came to exist.

    ``CONFIRMED`` means direct syntax proved it. ``INFERRED`` means HANA
    deduced it from a convention or heuristic. ``MANUAL`` means a human asserted
    it. Nothing is ever silently promoted between these.
    """

    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    MANUAL = "manual"


class FileAnalysisStatus(StrEnum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    FAILED = "failed"
    SKIPPED = "skipped"
    DELETED = "deleted"


class ChangeKind(StrEnum):
    """Result of comparing a scanned file against what the database remembers."""

    ADDED = "added"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"
    DELETED = "deleted"


class ProjectStatus(StrEnum):
    CREATED = "created"
    SCANNING = "scanning"
    ANALYZING = "analyzing"
    READY = "ready"
    ERROR = "error"


class AnalysisRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Severity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


class SkipReason(StrEnum):
    """Why the scanner refused to hash or analyse a file."""

    IGNORED_DIRECTORY = "ignored_directory"
    TOO_LARGE = "too_large"
    TOO_DEEP = "too_deep"
    BINARY = "binary"
    SYMLINK_ESCAPE = "symlink_escape"
    UNREADABLE = "unreadable"
