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
from .query.impact import DEFAULT_DEPTH


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


def command_impact(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    entity = _resolve_one(engine, args)
    if entity is None:
        return 2
    report = engine.queries.impact(
        entity.id,
        depth=args.depth,
        direction="outgoing" if args.reverse else "incoming",
        include_containment=args.containment,
    )
    if report is None:
        print(f"error: no existe la entidad {args.entity!r}", file=sys.stderr)
        return 2
    if args.json:
        _print(report.to_dict(), True)
        return 0

    question = "de qué depende" if args.reverse else "qué se rompe si cambia"
    print(f"{entity.name} — {question}:")
    if not report.nodes:
        print("  (nada llega hasta aquí)")
        return 0

    for entity_type, count in sorted(report.by_type.items()):
        print(f"  {count:>4}  {entity_type}")
    print()

    for node in report.nodes:
        evidence = node.evidence
        where = (
            f"{evidence['file_path']}:{evidence['start_line']}"
            if evidence.get("file_path")
            else "(sin archivo)"
        )
        # A path that crosses an inference must never read as certainty.
        flag = (
            f"  [inferido {node.min_confidence:.2f}]" if node.inferred_in_path else ""
        )
        print(
            f"  {node.depth}  {node.entity['entity_type']:<18}"
            f" {node.entity['name']:<34} {where}{flag}"
        )

    if report.truncated:
        print(
            "\n  AVISO: se alcanzó el límite de nodos; esta lista está incompleta.",
            file=sys.stderr,
        )
    return 0


def command_compare(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    report = engine.queries.compare(args.left, args.right, limit=args.limit)
    if report is None:
        print("error: alguno de los dos proyectos no existe", file=sys.stderr)
        return 2
    if args.json:
        _print(report.to_dict(), True)
        return 0

    # ASCII on purpose: the Windows console is cp1252 and an arrow raises.
    print(f"{report.left.name}  <->  {report.right.name}")
    print(
        f"  {report.left.entities} entidades / {report.left.relationships} relaciones"
        f"   ·   {report.right.entities} / {report.right.relationships}"
    )
    print(f"  en común: {report.shared_entities} entidades, {report.shared_relations} claims")
    print()

    # Printed before the differences, because it changes how they read.
    if report.warning:
        print(f"AVISO: {report.warning}")
        print()

    _print_side("Solo en " + report.left.name, report.entities_only_left, report.relations_only_left)
    _print_side("Solo en " + report.right.name, report.entities_only_right, report.relations_only_right)

    if not any(
        (
            report.entities_only_left,
            report.entities_only_right,
            report.relations_only_left,
            report.relations_only_right,
        )
    ):
        print("Los dos grafos dicen lo mismo.")
    if report.truncated:
        print("\n(alguna lista quedó recortada por el límite)")
    return 0


def _print_side(title: str, entities: dict, relations: dict) -> None:
    if not entities and not relations:
        return
    print(f"== {title} ==")
    for entity_type in sorted(entities):
        print(f"  {entity_type}")
        for hit in entities[entity_type]:
            where = f"{hit['file_path']}:{hit['start_line']}" if hit["file_path"] else ""
            print(f"      {hit['name']:<34} {where}")
    for relation_type in sorted(relations):
        print(f"  {relation_type}")
        for claim in relations[relation_type]:
            print(f"      {claim['source_name']} -> {claim['target_name']}")
    print()


def command_orphans(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    report = engine.queries.orphan_report(args.project_id, limit=args.limit)
    if args.json:
        _print(report, True)
        return 0

    print(f"Candidatos a revisar ({report['total']}):")
    print()
    for entity_type in sorted(report["by_type"]):
        hits = report["by_type"][entity_type]
        print(f"  {entity_type} ({len(hits)})")
        for hit in hits:
            where = (
                f"{hit['file_path']}:{hit['start_line']}"
                if hit["file_path"]
                else "(sin archivo)"
            )
            print(f"      {hit['name']:<34} {where}")
        print()
    if report["truncated"]:
        print("  (lista recortada por el límite)")
    # Printed last on purpose: it is the part that must not be skimmed past.
    print(report["caveat"])
    return 0


def command_annotate(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    entity = _resolve_one(engine, args)
    if entity is None:
        return 2
    verdict = "rejected" if args.reject else "confirmed"
    try:
        annotation = engine.annotate_entity(
            args.project_id, entity.id, verdict, note=args.note
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        _print(annotation.to_dict(), True)
        return 0
    label = "descartada" if verdict == "rejected" else "confirmada"
    print(f"{entity.entity_type} {entity.name}: inferencia {label}.")
    if args.note:
        print(f"  nota: {args.note}")
    print("  Sobrevivirá a los reanálisis.")
    return 0


def command_annotations(args: argparse.Namespace, engine: KnowledgeEngine) -> int:
    stored = engine.annotations(args.project_id)
    if args.json:
        _print(stored, True)
        return 0
    if not stored:
        print("(sin anotaciones)")
        return 0
    print(f"Anotaciones ({len(stored)}):")
    for item in stored:
        # An annotation matching nothing right now is worth seeing, not hiding.
        state = "" if item["resolved_id"] else "   (no coincide con nada ahora mismo)"
        print(f"  {item['verdict']:<10} {item['target_kind']:<13} {item['target_key']}{state}")
        if item["note"]:
            print(f"      {item['note']}")
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

    impact_parser = subparsers.add_parser(
        "impact", help="qué se rompe si cambia una entidad (transitivo)"
    )
    impact_parser.add_argument("project_id")
    impact_parser.add_argument("entity", help="nombre o id")
    impact_parser.add_argument(
        "--depth", type=int, default=DEFAULT_DEPTH, help="saltos a seguir"
    )
    impact_parser.add_argument(
        "--reverse", action="store_true", help="invertir: de qué depende ella"
    )
    impact_parser.add_argument(
        "--containment",
        action="store_true",
        help="seguir también las aristas de contención (arrastra el proyecto entero)",
    )
    impact_parser.set_defaults(handler=command_impact)

    compare_parser = subparsers.add_parser(
        "compare", help="diferencias entre dos proyectos analizados (DEV vs PROD)"
    )
    compare_parser.add_argument("left", help="id del primer proyecto")
    compare_parser.add_argument("right", help="id del segundo proyecto")
    compare_parser.add_argument("--limit", type=int, default=500)
    compare_parser.set_defaults(handler=command_compare)

    orphans_parser = subparsers.add_parser(
        "orphans", help="candidatos a revisar: nada del proyecto los referencia"
    )
    orphans_parser.add_argument("project_id")
    orphans_parser.add_argument("--limit", type=int, default=300)
    orphans_parser.set_defaults(handler=command_orphans)

    annotate_parser = subparsers.add_parser(
        "annotate", help="confirmar o descartar una inferencia"
    )
    annotate_parser.add_argument("project_id")
    annotate_parser.add_argument("entity", help="nombre o id")
    annotate_parser.add_argument(
        "--reject", action="store_true", help="descartarla en vez de confirmarla"
    )
    annotate_parser.add_argument("--note", help="por qué; es lo que da valor a la anotación")
    annotate_parser.set_defaults(handler=command_annotate)

    annotations_parser = subparsers.add_parser(
        "annotations", help="anotaciones registradas"
    )
    annotations_parser.add_argument("project_id")
    annotations_parser.set_defaults(handler=command_annotations)

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
