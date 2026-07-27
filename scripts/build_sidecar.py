#!/usr/bin/env python3
"""Freeze the Python engine into a standalone binary.

This is what lets the packaged application run on a machine with no Python
installed. The result is placed where Tauri expects an ``externalBin``:

    apps/desktop/src-tauri/binaries/hana-engine-<target-triple>[.exe]

Tauri requires the target triple suffix so that a bundle built for one platform
cannot accidentally ship another platform's binary. At install time Tauri copies
it next to the application executable, stripped back to ``hana-engine[.exe]``,
which is exactly where ``sidecar.rs`` looks for it.

Usage:
    python scripts/build_sidecar.py            # detect the host triple
    python scripts/build_sidecar.py --triple x86_64-pc-windows-msvc
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_ROOT = REPO_ROOT / "engine"
OUTPUT_DIR = REPO_ROOT / "apps" / "desktop" / "src-tauri" / "binaries"
BUILD_DIR = REPO_ROOT / "build" / "sidecar"

#: Launchers that import the package properly (see engine/sidecar_entry.py).
#:
#: Two products come out of the same code: the sidecar the desktop app drives
#: over stdio, and a command line a person can run directly. The CLI is what
#: makes the engine usable before the interface catches up.
ENTRY_POINTS = {
    "sidecar": (ENGINE_ROOT / "sidecar_entry.py", "hana-engine"),
    "cli": (ENGINE_ROOT / "cli_entry.py", "hana"),
}

#: Migrations are read at runtime from the package directory, so they have to
#: travel inside the bundle rather than being left behind on disk.
DATA_FILES = [
    (
        ENGINE_ROOT / "hana_engine" / "persistence" / "migrations",
        "hana_engine/persistence/migrations",
    )
]


def host_triple() -> str:
    """Ask rustc for the host target triple, which is what Tauri keys on."""
    try:
        output = subprocess.run(
            ["rustc", "-vV"], capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return _fallback_triple()

    for line in output.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    return _fallback_triple()


def _fallback_triple() -> str:
    """Best-effort triple when rustc is unavailable."""
    import platform

    machine = platform.machine().lower()
    arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    if sys.platform == "win32":
        return f"{arch}-pc-windows-msvc"
    if sys.platform == "darwin":
        return f"{arch}-apple-darwin"
    return f"{arch}-unknown-linux-gnu"


def build(triple: str, *, clean: bool, product: str = "sidecar") -> Path:
    entry_point, binary_name = ENTRY_POINTS[product]
    if not entry_point.exists():
        raise SystemExit(f"no se encontró el punto de entrada: {entry_point}")

    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "falta PyInstaller. Instálalo con:  python -m pip install pyinstaller"
        ) from exc

    if clean and BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    separator = ";" if os.name == "nt" else ":"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        binary_name,
        "--distpath",
        str(BUILD_DIR / "dist"),
        "--workpath",
        str(BUILD_DIR / "work"),
        "--specpath",
        str(BUILD_DIR),
        # Console subsystem on every platform, including Windows. PyInstaller's
        # windowed mode leaves sys.stdout/sys.stderr without a usable stream,
        # which would silently break a process whose entire protocol is stdio.
        # The host hides the window instead, by spawning with CREATE_NO_WINDOW
        # (see sidecar.rs) — same result, working pipes.
        "--console",
        "--noconfirm",
        "--clean",
        # The registry resolves analyzers at runtime, so PyInstaller's static
        # analysis cannot see them; pull the whole package in explicitly.
        "--collect-submodules",
        "hana_engine",
        "--paths",
        str(ENGINE_ROOT),
    ]

    for source, destination in DATA_FILES:
        command += ["--add-data", f"{source}{separator}{destination}"]

    command.append(str(entry_point))

    print(f"==> Congelando '{binary_name}' con PyInstaller")
    subprocess.run(command, check=True, cwd=ENGINE_ROOT)

    suffix = ".exe" if os.name == "nt" else ""
    produced = BUILD_DIR / "dist" / f"{binary_name}{suffix}"
    if not produced.exists():
        raise SystemExit(f"PyInstaller no produjo {produced}")

    # Only the sidecar needs Tauri's target-triple naming; the CLI is a plain
    # tool a person runs, so it keeps its simple name.
    if product == "cli":
        target = OUTPUT_DIR / f"{binary_name}{suffix}"
        shutil.copy2(produced, target)
        target.chmod(0o755)
        return target

    target = OUTPUT_DIR / f"hana-engine-{triple}{suffix}"
    shutil.copy2(produced, target)
    target.chmod(0o755)
    return target


def verify(binary: Path, product: str) -> None:
    """Prove the frozen binary actually works before it is shipped."""
    print("==> Verificando el binario")
    if product == "cli":
        result = subprocess.run(
            [str(binary), "status"], capture_output=True, text=True, timeout=180
        )
        if "version" not in result.stdout:
            raise SystemExit(
                "la CLI no respondió a 'status':\n"
                f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
            )
    else:
        probe = '{"id":"1","method":"engine.ping"}\n'
        result = subprocess.run(
            [str(binary), str(BUILD_DIR / "verify.db")],
            input=probe,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if '"pong":true' not in result.stdout.replace(" ", ""):
            raise SystemExit(
                "el binario no respondió al ping:\n"
                f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
            )
    print("    responde correctamente")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--triple", default=None, help="target triple de Rust")
    parser.add_argument(
        "--product",
        choices=sorted(ENTRY_POINTS),
        default="sidecar",
        help="'sidecar' para la aplicación, 'cli' para la herramienta de terminal",
    )
    parser.add_argument("--no-clean", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args()

    triple = args.triple or host_triple()
    print(f"==> Target triple: {triple}")

    binary = build(triple, clean=not args.no_clean, product=args.product)
    if not args.skip_verify:
        verify(binary, args.product)

    size_mb = binary.stat().st_size / (1024 * 1024)
    print(f"\nListo: {binary}  ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
