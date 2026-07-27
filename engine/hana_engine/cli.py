"""Headless command line for the engine.

Everything the desktop app can do to a project, this CLI can do without Tauri,
Node or a display. It is the fastest way to reproduce a bug and the reference
implementation of the engine's public surface.

    python -m hana_engine.cli open ./my-project
    python -m hana_engine.cli analyze <project-id>
    python -m hana_engine.cli status
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .engine import KnowledgeEngine, ProjectPathError
from .indexing.policy import ScanPolicy
from .indexing.scanner import scan_project
from .pipeline.orchestrator import ProgressEvent


def _print(value: Any, as_json: bool) -> None:
    if as_json:
        json.dump(value, sys.stdout, ensure_ascii=False, indent=2, default=str)
        sys.stdout.write("\n")
        return
    if isinstance(value, dict):
        width = max((len(key) for key in value), default=0)
        for key, item in value.items():
            print(f"  {key.ljust(width)} : {item}")
    elif isinstance(value, list):
        for item in value:
            print(f"  - {item}")
    else:
        print(value)


def _progress_printer() -> Any:
    last_phase = {"value": ""}

    def report(event: ProgressEvent) -> None:
        if event.phase != last_phase["value"]:
            last_phase["value"] = event.phase
            print(f"[{event.phase}]", file=sys.stderr)
        total = f"/{event.total}" if event.total else ""
        print(
            f"  {event.current}{total} {event.message}"[:120],
            file=sys.stderr,
        )

    return report


def command_open(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    try:
        project = engine.open_project(args.path, args.name)
    except ProjectPathError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _print(
        {
            "id": project.id,
            "name": project.name,
            "root_path": project.root_path,
            "status": project.status.value,
            "type": project.project_type,
        },
        args.json,
    )
    return 0


def command_analyze(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    run = engine.analyze_project(
        args.project_id,
        trigger=args.trigger,
        on_progress=None if args.quiet else _progress_printer(),
    )
    _print(
        {
            "run_id": run.id,
            "status": run.status.value,
            "files_scanned": run.files_scanned,
            "added": run.files_added,
            "modified": run.files_modified,
            "unchanged": run.files_unchanged,
            "deleted": run.files_deleted,
            "analyzed": run.files_analyzed,
            "entities_created": run.entities_created,
            "relationships_created": run.relationships_created,
            "errors": run.error_count,
        },
        args.json,
    )
    return 0 if run.status.value in ("completed", "cancelled") else 1


def command_scan(args: argparse.Namespace, _engine: KnowledgeEngine) -> int:
    """Dry run: walk a folder and report what would be inventoried."""
    report = scan_project(args.path, ScanPolicy())
    _print(
        {
            "root": report.root,
            "files": len(report.files),
            "skipped": len(report.skipped),
            "directories": report.directories_visited,
            "bytes_hashed": report.bytes_hashed,
            "errors": len(report.errors),
        },
        args.json,
    )
    if args.list:
        for scanned in report.files[: args.limit]:
            print(f"  {scanned.content_hash[:12]}  {scanned.relative_path}")
    return 0


def command_status(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    _print(engine.status().to_dict(), args.json)
    return 0


def command_projects(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    projects = engine.recent_projects(args.limit)
    if args.json:
        _print(
            [
                {
                    "id": p.id,
                    "name": p.name,
                    "root_path": p.root_path,
                    "status": p.status.value,
                    "last_analysis_at": p.last_analysis_at,
                }
                for p in projects
            ],
            True,
        )
        return 0
    if not projects:
        print("  (sin proyectos)")
        return 0
    for project in projects:
        marker = project.last_analysis_at or "nunca analizado"
        print(f"  {project.id}  {project.name:<28} {marker}  {project.root_path}")
    return 0


def command_stats(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    _print(engine.project_stats(args.project_id).to_dict(), args.json)
    return 0


def command_history(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    runs = engine.analysis_history(args.project_id, args.limit)
    _print(
        [
            {
                "id": run.id,
                "status": run.status.value,
                "started_at": run.started_at,
                "added": run.files_added,
                "modified": run.files_modified,
                "deleted": run.files_deleted,
                "errors": run.error_count,
            }
            for run in runs
        ],
        args.json,
    )
    return 0


# ---------------------------------------------------------------------------
# Consultas deterministas — las diez preguntas que HANA responde sin modelo
# ---------------------------------------------------------------------------
def _print_entities(hits, as_json: bool) -> None:
    if as_json:
        _print([hit.to_dict() for hit in hits], True)
        return
    if not hits:
        print("  (sin resultados)")
        return
    for hit in hits:
        location = f"{hit.file_path}:{hit.start_line}" if hit.file_path else ""
        flag = "" if hit.confidence >= 1.0 else f"  [{hit.verification_status} {hit.confidence:.2f}]"
        print(f"  {hit.entity_type:<18} {hit.name:<34} {location}{flag}")


def _print_usages(hits, as_json: bool) -> None:
    if as_json:
        _print([hit.to_dict() for hit in hits], True)
        return
    if not hits:
        print("  (sin resultados)")
        return
    for hit in hits:
        evidence = hit.evidence
        where = (
            f"{evidence.file_path}:{evidence.start_line}"
            if evidence.file_path
            else "(sin archivo)"
        )
        flag = "" if evidence.confidence >= 1.0 else f" [{evidence.status} {evidence.confidence:.2f}]"
        print(f"  {hit.relation_type:<28} {hit.entity.name:<32} {where}{flag}")
        if evidence.snippet:
            print(f"      {' '.join(evidence.snippet.split())[:110]}")


def _resolve_one(engine: KnowledgeEngine, args: argparse.Namespace):
    """Turn a name or an id into exactly one entity, or explain why not."""
    hit = engine.queries.get(args.entity)
    if hit is not None:
        return hit
    matches = engine.queries.resolve(args.project_id, args.entity)
    if not matches:
        print(f"error: no existe ninguna entidad llamada {args.entity!r}", file=sys.stderr)
        return None
    if len(matches) > 1:
        print(
            f"'{args.entity}' es ambiguo; usa el id de una de estas:", file=sys.stderr
        )
        for match in matches:
            print(f"  {match.id}  {match.entity_type:<18} {match.name}", file=sys.stderr)
        return None
    return matches[0]


def command_search(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    _print_entities(engine.queries.search(args.project_id, args.text), args.json)
    return 0


def command_uses(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    entity = _resolve_one(engine, args)
    if entity is None:
        return 2
    if not args.json:
        print(f"Usos de {entity.entity_type} {entity.name}:")
    _print_usages(engine.queries.where_used(entity.id), args.json)
    return 0


def command_depends(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    entity = _resolve_one(engine, args)
    if entity is None:
        return 2
    queries = engine.queries
    hits = queries.dependencies(entity.id) if args.on else queries.dependents(entity.id)
    if not args.json:
        label = "depende de" if args.on else "de lo que depende"
        print(f"{entity.name} — {label}:")
    _print_usages(hits, args.json)
    return 0


def command_tables(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    written = True if args.writes else (False if args.reads else None)
    hits = engine.queries.tables_of_file(args.project_id, args.file, written=written)
    if not args.json:
        print(f"Tablas que toca {args.file}:")
    _print_usages(hits, args.json)
    return 0


def command_items(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    hits = engine.queries.apex_items_in_file(args.project_id, args.file)
    if not args.json:
        print(f"Items APEX en {args.file}:")
    _print_entities(hits, args.json)
    return 0


def command_reports(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    entity = _resolve_one(engine, args)
    if entity is None:
        return 2
    if not args.json:
        print(f"Reportes que utilizan {entity.name}:")
    _print_usages(engine.queries.reports_using_table(entity.id), args.json)
    return 0


def command_images(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    entity = _resolve_one(engine, args)
    if entity is None:
        return 2
    if not args.json:
        print(f"Imágenes que utiliza {entity.name}:")
    _print_usages(engine.queries.images_of_report(entity.id), args.json)
    return 0


def command_changes(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    result = engine.queries.changes_since(args.project_id, run_id=args.run)
    if args.json:
        _print(result, True)
        return 0
    if not result["changes"]:
        print("  (sin cambios registrados)")
        return 0
    for change in result["changes"]:
        print(f"  {change['change_kind']:<10} {change['relative_path']}")
    return 0


def command_errors(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    rows = engine.queries.files_with_errors(args.project_id, severity=args.severity)
    if args.json:
        _print(rows, True)
        return 0
    if not rows:
        print("  (sin errores de análisis)")
        return 0
    for row in rows:
        print(f"  {row['severity']:<8} {row['relative_path'] or '(proyecto)':<44} {row['code']}")
        print(f"      {row['message']}")
    return 0


def command_review(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    """Entities whose confidence says a human should look."""
    hits = engine.queries.low_confidence(args.project_id, threshold=args.threshold)
    if not args.json:
        print(f"Entidades con confianza menor que {args.threshold}:")
    _print_entities(hits, args.json)
    return 0


def command_graph(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    entity = _resolve_one(engine, args)
    if entity is None:
        return 2
    result = engine.queries.neighborhood(entity.id, depth=args.depth)
    if args.json:
        _print(result.to_dict(), True)
        return 0
    print(f"Vecindario de {entity.name} (profundidad {args.depth}):")
    for node in result.nodes:
        print(f"  {'  ' * node.depth}{node.entity.entity_type:<18} {node.entity.name}")
    print(f"  — {len(result.nodes)} nodos, {len(result.edges)} aristas"
          + ("  (truncado)" if result.truncated else ""))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hana",
        description="HANA Knowledge Engine — motor de conocimiento local",
    )
    parser.add_argument("--db", help="ruta de la base de conocimiento")
    parser.add_argument("--json", action="store_true", help="salida en JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    open_parser = subparsers.add_parser("open", help="registrar o abrir un proyecto")
    open_parser.add_argument("path")
    open_parser.add_argument("--name")
    open_parser.set_defaults(handler=command_open)

    analyze_parser = subparsers.add_parser("analyze", help="analizar un proyecto")
    analyze_parser.add_argument("project_id")
    analyze_parser.add_argument("--trigger", default="cli")
    analyze_parser.add_argument("--quiet", action="store_true")
    analyze_parser.set_defaults(handler=command_analyze)

    scan_parser = subparsers.add_parser("scan", help="escanear sin persistir nada")
    scan_parser.add_argument("path")
    scan_parser.add_argument("--list", action="store_true")
    scan_parser.add_argument("--limit", type=int, default=50)
    scan_parser.set_defaults(handler=command_scan)

    status_parser = subparsers.add_parser("status", help="estado del motor")
    status_parser.set_defaults(handler=command_status)

    projects_parser = subparsers.add_parser("projects", help="proyectos recientes")
    projects_parser.add_argument("--limit", type=int, default=20)
    projects_parser.set_defaults(handler=command_projects)

    stats_parser = subparsers.add_parser("stats", help="métricas de un proyecto")
    stats_parser.add_argument("project_id")
    stats_parser.set_defaults(handler=command_stats)

    # --- las diez consultas deterministas ---------------------------------
    search_parser = subparsers.add_parser("search", help="buscar entidades")
    search_parser.add_argument("project_id")
    search_parser.add_argument("text")
    search_parser.set_defaults(handler=command_search)

    uses_parser = subparsers.add_parser("uses", help="dónde se utiliza una entidad")
    uses_parser.add_argument("project_id")
    uses_parser.add_argument("entity", help="nombre o id")
    uses_parser.set_defaults(handler=command_uses)

    depends_parser = subparsers.add_parser("depends", help="qué depende de una entidad")
    depends_parser.add_argument("project_id")
    depends_parser.add_argument("entity")
    depends_parser.add_argument(
        "--on", action="store_true", help="invertir: de qué depende ella"
    )
    depends_parser.set_defaults(handler=command_depends)

    tables_parser = subparsers.add_parser("tables", help="tablas que toca un archivo")
    tables_parser.add_argument("project_id")
    tables_parser.add_argument("file", help="ruta relativa dentro del proyecto")
    tables_parser.add_argument("--reads", action="store_true", help="solo lecturas")
    tables_parser.add_argument("--writes", action="store_true", help="solo escrituras")
    tables_parser.set_defaults(handler=command_tables)

    items_parser = subparsers.add_parser("items", help="items APEX de un archivo")
    items_parser.add_argument("project_id")
    items_parser.add_argument("file")
    items_parser.set_defaults(handler=command_items)

    reports_parser = subparsers.add_parser("reports", help="reportes que usan una tabla")
    reports_parser.add_argument("project_id")
    reports_parser.add_argument("entity")
    reports_parser.set_defaults(handler=command_reports)

    images_parser = subparsers.add_parser("images", help="imágenes de un reporte")
    images_parser.add_argument("project_id")
    images_parser.add_argument("entity")
    images_parser.set_defaults(handler=command_images)

    changes_parser = subparsers.add_parser("changes", help="qué cambió en un análisis")
    changes_parser.add_argument("project_id")
    changes_parser.add_argument("--run", help="id de la ejecución; por omisión la última")
    changes_parser.set_defaults(handler=command_changes)

    errors_parser = subparsers.add_parser("errors", help="errores de análisis")
    errors_parser.add_argument("project_id")
    errors_parser.add_argument("--severity", choices=["error", "warning"])
    errors_parser.set_defaults(handler=command_errors)

    review_parser = subparsers.add_parser("review", help="entidades de baja confianza")
    review_parser.add_argument("project_id")
    review_parser.add_argument("--threshold", type=float, default=0.8)
    review_parser.set_defaults(handler=command_review)

    graph_parser = subparsers.add_parser("graph", help="vecindario de una entidad")
    graph_parser.add_argument("project_id")
    graph_parser.add_argument("entity")
    graph_parser.add_argument("--depth", type=int, default=1)
    graph_parser.set_defaults(handler=command_graph)

    history_parser = subparsers.add_parser("history", help="historial de análisis")
    history_parser.add_argument("project_id")
    history_parser.add_argument("--limit", type=int, default=10)
    history_parser.set_defaults(handler=command_history)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with KnowledgeEngine(args.db) as engine:
        return int(args.handler(args, engine))


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
