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
