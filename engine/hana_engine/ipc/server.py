"""JSON-Lines sidecar.

The desktop app talks to the engine over stdin/stdout, one JSON object per line.
No sockets, no ports, no HTTP server — which is both simpler to package and the
reason HANA opens no network listener at all.

Wire format
-----------
Request   ``{"id": "1", "method": "project.open", "params": {...}}``
Response  ``{"id": "1", "ok": true, "result": {...}}``
Error     ``{"id": "1", "ok": false, "error": {"code": "...", "message": "..."}}``
Event     ``{"event": "progress", "data": {...}}``  (unsolicited, no id)

Threading
---------
The reader thread only parses lines. Every call that touches SQLite is queued to
one worker thread that owns the connection, because a SQLite connection belongs
to the thread that created it. ``analysis.cancel`` is the sole exception: it just
sets a flag, so it is handled inline and stays responsive while a long analysis
occupies the worker.
"""

from __future__ import annotations

import dataclasses
import json
import queue
import sys
import threading
import traceback
from collections.abc import Callable, Iterable
from typing import Any, TextIO

from ..domain.models import ScannedFile
from ..domain.types import EntityType
from ..engine import KnowledgeEngine, ProjectPathError
from ..indexing.policy import ScanPolicy
from ..models.provider import get_provider
from ..pipeline.orchestrator import CancellationToken, ProgressEvent

PROTOCOL_VERSION = 1

#: U+FEFF, the byte-order mark. Built with ``chr`` so this source file contains
#: no non-ASCII character of its own: an earlier version embedded the literal
#: BOM, the file was saved mojibake as three Latin-1 characters, and the strip
#: silently removed nothing. A constant that cannot be corrupted by an encoding
#: is worth the extra line.
_BOM = chr(0xFEFF)


def _encode(value: Any) -> Any:
    """Make a domain object JSON-serialisable.

    The enums in ``domain.types`` subclass ``str``, so ``json`` already emits
    their values; only dataclasses and containers need walking.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _encode(getattr(value, field.name))
            for field in dataclasses.fields(value)
            if not field.name.startswith("_")
        }
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    return value


class LineWriter:
    """Serialises writes so the worker and the reader cannot interleave lines.

    Frames are emitted as **pure ASCII**: ``ensure_ascii=True`` escapes every
    non-ASCII character as ``\\uXXXX``. That is not a stylistic choice, it is what
    makes the protocol independent of whatever encoding the process happens to
    get. Emitting raw characters made a progress message like "Comparando con el
    análisis anterior" leave as a lone ``0xE1`` byte whenever stdout defaulted to
    a legacy codepage; the host then failed to decode the line, gave up on the
    stream, and every pending request died with "the engine stopped" while the
    analysis appeared to hang forever.
    """

    def __init__(self, stream: TextIO) -> None:
        # Belt and braces: ask for UTF-8 as well, so anything that bypasses the
        # ASCII escaping (a traceback, a third-party write) is still decodable.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (ValueError, OSError):
                pass
        self._stream = stream
        self._lock = threading.Lock()

    def send(self, payload: dict[str, Any]) -> None:
        line = json.dumps(_encode(payload), ensure_ascii=True, separators=(",", ":"))
        with self._lock:
            self._stream.write(line + "\n")
            self._stream.flush()


class RpcError(Exception):
    """An error that should reach the client as a structured response."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class EngineServer:
    """Dispatches JSON-Lines requests to a :class:`KnowledgeEngine`."""

    def __init__(
        self,
        engine: KnowledgeEngine | None = None,
        *,
        db_path: str | None = None,
        writer: LineWriter | None = None,
    ) -> None:
        self._engine = engine
        self._db_path = db_path
        self.writer = writer or LineWriter(sys.stdout)
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._cancellations: dict[str, CancellationToken] = {}
        self._cancel_lock = threading.Lock()
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "engine.status": self._engine_status,
            "engine.ping": lambda params: {"pong": True, "protocol": PROTOCOL_VERSION},
            "project.open": self._project_open,
            "project.list": self._project_list,
            "project.get": self._project_get,
            "project.stats": self._project_stats,
            "project.files": self._project_files,
            "project.delete": self._project_delete,
            "project.scan_policy.get": self._scan_policy_get,
            "project.scan_policy.set": self._scan_policy_set,
            "analysis.run": self._analysis_run,
            "analysis.history": self._analysis_history,
            "analysis.latest": self._analysis_latest,
            "model.status": self._model_status,
            # The answering layer. Deterministic: every result is computed from
            # stored facts, and carries the file and lines that prove it.
            "query.search": self._query_search,
            "query.resolve": self._query_resolve,
            "query.entity": self._query_entity,
            "query.uses": self._query_uses,
            "query.dependents": self._query_dependents,
            "query.dependencies": self._query_dependencies,
            "query.tables_of_file": self._query_tables_of_file,
            "query.entities_in_file": self._query_entities_in_file,
            "query.reports_using_table": self._query_reports_using_table,
            "query.images_of_report": self._query_images_of_report,
            "query.changes": self._query_changes,
            "query.errors": self._query_errors,
            "query.low_confidence": self._query_low_confidence,
            "query.neighborhood": self._query_neighborhood,
            "query.er_model": self._query_er_model,
            "query.report_structure": self._query_report_structure,
            "query.freshness": self._query_freshness,
        }

    # -- lifecycle ----------------------------------------------------------

    @property
    def engine(self) -> KnowledgeEngine:
        if self._engine is None:
            self._engine = KnowledgeEngine(self._db_path)
        return self._engine

    def serve(self, stream: Iterable[str] | None = None) -> None:
        """Read requests until the input closes."""
        worker = threading.Thread(target=self._work, name="hana-engine", daemon=True)
        worker.start()

        source = stream if stream is not None else sys.stdin
        self.writer.send(
            {"event": "ready", "data": {"protocol": PROTOCOL_VERSION}}
        )
        try:
            for line in source:
                text = line.strip()
                if not text:
                    continue
                self._accept(text)
        finally:
            self._queue.put(None)
            worker.join(timeout=10)

    def _accept(self, text: str) -> None:
        # PowerShell emits a UTF-8 BOM at the start of a stream when piping to a
        # native executable, and plenty of Windows tooling writes one into files.
        # Those three bytes are not JSON, so without this the *first* request of
        # every such client failed while the rest went through — a baffling
        # symptom for whoever hits it.
        text = text.lstrip(_BOM)
        try:
            request = json.loads(text)
        except json.JSONDecodeError as exc:
            self.writer.send(
                {
                    "id": None,
                    "ok": False,
                    "error": {"code": "invalid_json", "message": str(exc)},
                }
            )
            return
        if not isinstance(request, dict):
            self.writer.send(
                {
                    "id": None,
                    "ok": False,
                    "error": {
                        "code": "invalid_request",
                        "message": "expected a JSON object",
                    },
                }
            )
            return

        # Handled on the reader thread on purpose: cancelling must work while the
        # worker is busy analysing.
        if request.get("method") == "analysis.cancel":
            self._respond(request.get("id"), self._analysis_cancel(request.get("params") or {}))
            return

        self._queue.put(request)

    def _work(self) -> None:
        while True:
            request = self._queue.get()
            if request is None:
                return
            self._handle(request)

    def _handle(self, request: dict[str, Any]) -> None:
        request_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params") or {}
        handler = self._handlers.get(method)

        if handler is None:
            self.writer.send(
                {
                    "id": request_id,
                    "ok": False,
                    "error": {
                        "code": "unknown_method",
                        "message": f"método desconocido: {method}",
                    },
                }
            )
            return

        try:
            self._respond(request_id, handler(params))
        except RpcError as exc:
            self.writer.send(
                {
                    "id": request_id,
                    "ok": False,
                    "error": {"code": exc.code, "message": exc.message},
                }
            )
        except Exception as exc:  # noqa: BLE001 - a crash must not kill the sidecar
            self.writer.send(
                {
                    "id": request_id,
                    "ok": False,
                    "error": {
                        "code": "internal_error",
                        "message": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(limit=8),
                    },
                }
            )

    def _respond(self, request_id: Any, result: Any) -> None:
        self.writer.send({"id": request_id, "ok": True, "result": result})

    # -- handlers -----------------------------------------------------------

    def _engine_status(self, _params: dict[str, Any]) -> dict[str, Any]:
        return self.engine.status().to_dict()

    def _project_open(self, params: dict[str, Any]) -> dict[str, Any]:
        path = params.get("path")
        if not path:
            raise RpcError("missing_param", "se requiere 'path'")
        try:
            project = self.engine.open_project(path, params.get("name"))
        except ProjectPathError as exc:
            raise RpcError("invalid_path", str(exc)) from exc
        return _encode(project)

    def _project_list(self, params: dict[str, Any]) -> list[Any]:
        return [
            _encode(project)
            for project in self.engine.recent_projects(int(params.get("limit", 20)))
        ]

    def _project_get(self, params: dict[str, Any]) -> Any:
        project = self.engine.get_project(self._require(params, "project_id"))
        if project is None:
            raise RpcError("not_found", "proyecto no encontrado")
        return _encode(project)

    def _project_stats(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.engine.project_stats(self._require(params, "project_id")).to_dict()

    def _project_files(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return self.engine.file_tree(self._require(params, "project_id"))

    def _project_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        self.engine.delete_project(self._require(params, "project_id"))
        return {"deleted": True}

    def _scan_policy_get(self, params: dict[str, Any]) -> dict[str, Any]:
        project = self.engine.get_project(self._require(params, "project_id"))
        if project is None:
            raise RpcError("not_found", "proyecto no encontrado")
        return self.engine.scan_policy_for(project).to_dict()

    def _scan_policy_set(self, params: dict[str, Any]) -> dict[str, Any]:
        project_id = self._require(params, "project_id")
        policy = ScanPolicy.from_dict(params.get("policy") or {})
        self.engine.update_scan_policy(project_id, policy)
        return policy.to_dict()

    def _analysis_run(self, params: dict[str, Any]) -> dict[str, Any]:
        project_id = self._require(params, "project_id")
        raw_files = params.get("scanned_files")
        scanned = (
            [ScannedFile.from_dict(item) for item in raw_files]
            if raw_files is not None
            else None
        )

        token = CancellationToken()
        with self._cancel_lock:
            self._cancellations[project_id] = token

        def on_progress(event: ProgressEvent) -> None:
            self.writer.send({"event": "progress", "data": event.to_dict()})

        try:
            run = self.engine.analyze_project(
                project_id,
                scanned_files=scanned,
                trigger=params.get("trigger", "manual"),
                on_progress=on_progress,
                cancellation=token,
            )
        except ProjectPathError as exc:
            raise RpcError("not_found", str(exc)) from exc
        finally:
            with self._cancel_lock:
                self._cancellations.pop(project_id, None)

        payload = _encode(run)
        self.writer.send({"event": "analysis.finished", "data": payload})
        return payload

    def _analysis_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        project_id = params.get("project_id")
        with self._cancel_lock:
            tokens = (
                [self._cancellations[project_id]]
                if project_id in self._cancellations
                else list(self._cancellations.values())
                if project_id is None
                else []
            )
        for token in tokens:
            token.cancel()
        return {"cancelled": len(tokens)}

    def _analysis_history(self, params: dict[str, Any]) -> list[Any]:
        return [
            _encode(run)
            for run in self.engine.analysis_history(
                self._require(params, "project_id"), int(params.get("limit", 25))
            )
        ]

    def _analysis_latest(self, params: dict[str, Any]) -> Any:
        run = self.engine.latest_run(self._require(params, "project_id"))
        return _encode(run) if run else None

    def _model_status(self, params: dict[str, Any]) -> dict[str, Any]:
        provider = get_provider(params.get("provider", "disabled"))
        return {
            "id": provider.id,
            "label": provider.label,
            "available": provider.is_available(),
            "models": [_encode(model) for model in provider.list_models()],
        }

    # -- the answering layer ------------------------------------------------

    def _query_search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        hits = self.engine.queries.search(
            self._require(params, "project_id"),
            str(params.get("text", "")),
            limit=int(params.get("limit", 50)),
        )
        return [hit.to_dict() for hit in hits]

    def _query_resolve(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        entity_type = params.get("entity_type")
        hits = self.engine.queries.resolve(
            self._require(params, "project_id"),
            self._require(params, "name"),
            entity_type=EntityType(entity_type) if entity_type else None,
        )
        return [hit.to_dict() for hit in hits]

    def _query_entity(self, params: dict[str, Any]) -> dict[str, Any] | None:
        hit = self.engine.queries.get(self._require(params, "entity_id"))
        return hit.to_dict() if hit else None

    def _query_uses(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        hits = self.engine.queries.where_used(
            self._require(params, "entity_id"),
            include_structural=bool(params.get("include_structural", False)),
            limit=int(params.get("limit", 200)),
        )
        return [hit.to_dict() for hit in hits]

    def _query_dependents(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        hits = self.engine.queries.dependents(self._require(params, "entity_id"))
        return [hit.to_dict() for hit in hits]

    def _query_dependencies(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        hits = self.engine.queries.dependencies(self._require(params, "entity_id"))
        return [hit.to_dict() for hit in hits]

    def _query_tables_of_file(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        written = params.get("written")
        hits = self.engine.queries.tables_of_file(
            self._require(params, "project_id"),
            self._require(params, "relative_path"),
            written=None if written is None else bool(written),
        )
        return [hit.to_dict() for hit in hits]

    def _query_entities_in_file(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        entity_type = params.get("entity_type")
        hits = self.engine.queries.entities_in_file(
            self._require(params, "project_id"),
            self._require(params, "relative_path"),
            entity_type=EntityType(entity_type) if entity_type else None,
        )
        return [hit.to_dict() for hit in hits]

    def _query_reports_using_table(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        hits = self.engine.queries.reports_using_table(
            self._require(params, "entity_id")
        )
        return [hit.to_dict() for hit in hits]

    def _query_images_of_report(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        hits = self.engine.queries.images_of_report(self._require(params, "entity_id"))
        return [hit.to_dict() for hit in hits]

    def _query_changes(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.engine.queries.changes_since(
            self._require(params, "project_id"), run_id=params.get("run_id")
        )

    def _query_errors(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return self.engine.queries.files_with_errors(
            self._require(params, "project_id"), severity=params.get("severity")
        )

    def _query_low_confidence(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        hits = self.engine.queries.low_confidence(
            self._require(params, "project_id"),
            threshold=float(params.get("threshold", 0.8)),
        )
        return [hit.to_dict() for hit in hits]

    def _query_neighborhood(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.engine.queries.neighborhood(
            self._require(params, "entity_id"),
            depth=int(params.get("depth", 1)),
            max_nodes=int(params.get("max_nodes", 150)),
        ).to_dict()

    def _query_er_model(self, params: dict[str, Any]) -> dict[str, Any]:
        table_ids = params.get("table_ids")
        return self.engine.queries.er_model(
            self._require(params, "project_id"),
            table_ids=list(table_ids) if table_ids else None,
        )

    def _query_report_structure(self, params: dict[str, Any]) -> dict[str, Any] | None:
        return self.engine.queries.report_structure(self._require(params, "entity_id"))

    def _query_freshness(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.engine.queries.freshness(self._require(params, "project_id"))

    @staticmethod
    def _require(params: dict[str, Any], key: str) -> str:
        value = params.get(key)
        if not value:
            raise RpcError("missing_param", f"se requiere '{key}'")
        return str(value)


def main(argv: list[str] | None = None) -> int:
    """Entry point used by the Tauri host: ``python -m hana_engine.ipc.server``."""
    args = argv if argv is not None else sys.argv[1:]
    db_path = args[0] if args else None
    EngineServer(db_path=db_path).serve()
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
