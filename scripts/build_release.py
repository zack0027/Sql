#!/usr/bin/env python3
"""Build a distributable HANA, signed when a certificate is available.

Runs the whole chain in the one order that produces a coherently signed result:

  1. freeze the engine and the CLI with PyInstaller
  2. sign those binaries, *before* Tauri bundles them — an installer signed
     around unsigned contents is worse than no signature, because it looks
     trustworthy and its payload is not
  3. build the app and the installer, letting Tauri sign both

Signing is driven entirely by the environment, so the certificate never enters
the repository:

    HANA_SIGN_THUMBPRINT   SHA-1 thumbprint of a certificate in the Windows
                           store (``certutil -store My``). Preferred: the private
                           key can stay non-exportable.
    HANA_SIGN_PFX          Path to a .pfx file, if the certificate is not in the
                           store.
    HANA_SIGN_PASSWORD     Password for that .pfx.
    HANA_SIGN_TIMESTAMP    RFC 3161 timestamp server. Defaults to DigiCert's.

With none of these set the build runs unsigned and says so. That is the normal
case for an internal tool, and Windows SmartScreen will warn the first users —
see docs/FIRMA_DE_CODIGO.md.

Usage:
    python scripts/build_release.py
    python scripts/build_release.py --bundles nsis
    python scripts/build_release.py --skip-cli
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DESKTOP = REPO_ROOT / "apps" / "desktop"
BINARIES = DESKTOP / "src-tauri" / "binaries"

DEFAULT_TIMESTAMP = "http://timestamp.digicert.com"


class BuildError(RuntimeError):
    """A step failed; the message is meant for a person, not a stack trace."""


# ---------------------------------------------------------------------------
# signing


def signing_configured() -> bool:
    return bool(os.environ.get("HANA_SIGN_THUMBPRINT") or os.environ.get("HANA_SIGN_PFX"))


def find_signtool() -> Path | None:
    """Locate signtool.exe, which ships with the Windows SDK rather than Windows.

    Searched by hand because it is not on PATH in a default install, and the
    error "signtool no encontrado" is far more useful than whatever a missing
    executable produces three layers down.
    """
    found = shutil.which("signtool")
    if found:
        return Path(found)

    roots = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
    ]
    candidates: list[Path] = []
    for root in roots:
        kits = root / "Windows Kits" / "10" / "bin"
        if not kits.is_dir():
            continue
        candidates.extend(kits.glob("*/x64/signtool.exe"))

    # Newest SDK last, so sorting and taking the end picks the current one.
    return sorted(candidates)[-1] if candidates else None


def sign(paths: list[Path]) -> None:
    """Authenticode-sign each path in place."""
    if not paths:
        return

    signtool = find_signtool()
    if signtool is None:
        raise BuildError(
            "no se encontró signtool.exe.\n"
            "    Instala el Windows SDK, o desactiva la firma quitando "
            "HANA_SIGN_THUMBPRINT / HANA_SIGN_PFX del entorno."
        )

    command = [str(signtool), "sign", "/fd", "sha256", "/td", "sha256"]

    thumbprint = os.environ.get("HANA_SIGN_THUMBPRINT")
    pfx = os.environ.get("HANA_SIGN_PFX")
    if thumbprint:
        command += ["/sha1", thumbprint]
    elif pfx:
        command += ["/f", pfx]
        password = os.environ.get("HANA_SIGN_PASSWORD")
        if password:
            command += ["/p", password]

    # A signature without a timestamp expires with the certificate; one with a
    # timestamp stays valid for the life of the binary.
    command += ["/tr", os.environ.get("HANA_SIGN_TIMESTAMP", DEFAULT_TIMESTAMP)]
    command += [str(path) for path in paths]

    print(f"==> Firmando {len(paths)} binario(s)")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise BuildError(f"signtool falló:\n{result.stdout}\n{result.stderr}")
    for path in paths:
        print(f"    firmado: {path.name}")


# ---------------------------------------------------------------------------
# steps


def run(command: list[str], *, cwd: Path) -> None:
    print(f"==> {' '.join(command)}")
    result = subprocess.run(command, cwd=cwd)
    if result.returncode != 0:
        raise BuildError(f"falló: {' '.join(command)}")


def freeze(product: str, triple: str | None) -> None:
    command = [sys.executable, str(REPO_ROOT / "scripts" / "build_sidecar.py"),
               "--product", product]
    if triple:
        command += ["--triple", triple]
    run(command, cwd=REPO_ROOT)


def tauri_build(triple: str | None, bundles: str) -> None:
    command = ["pnpm", "exec", "tauri", "build", "--bundles", bundles]
    if triple:
        command += ["--target", triple]

    # Tauri signs the application and the installer itself when the config names
    # a certificate. Passing it here instead of writing it into tauri.conf.json
    # keeps the thumbprint out of the repository.
    thumbprint = os.environ.get("HANA_SIGN_THUMBPRINT")
    if thumbprint:
        command += [
            "--config",
            '{"bundle":{"windows":{"certificateThumbprint":"%s",'
            '"digestAlgorithm":"sha256","timestampUrl":"%s"}}}'
            % (thumbprint, os.environ.get("HANA_SIGN_TIMESTAMP", DEFAULT_TIMESTAMP)),
        ]

    # pnpm is a .cmd on Windows; shell=False cannot launch it.
    print(f"==> {' '.join(command)}")
    result = subprocess.run(command, cwd=DESKTOP, shell=os.name == "nt")
    if result.returncode != 0:
        raise BuildError("la compilación de Tauri falló")


def frozen_binaries() -> list[Path]:
    return sorted(path for path in BINARIES.glob("hana*") if path.suffix in {".exe", ""})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--triple", default=None, help="target triple de Rust")
    parser.add_argument("--bundles", default="nsis", help="nsis, msi o 'nsis,msi'")
    parser.add_argument("--skip-cli", action="store_true",
                        help="no construir la herramienta de terminal")
    args = parser.parse_args()

    signed = signing_configured()
    print("==> Firma:", "configurada" if signed else "NO configurada (compilación sin firmar)")

    try:
        freeze("sidecar", args.triple)
        if not args.skip_cli:
            freeze("cli", args.triple)

        if signed:
            # Before bundling, or the installer would wrap unsigned executables.
            sign(frozen_binaries())

        tauri_build(args.triple, args.bundles)
    except BuildError as error:
        print(f"\nERROR: {error}", file=sys.stderr)
        return 1

    print("\nListo.")
    if not signed:
        print(
            "\nEste binario no está firmado. Windows SmartScreen avisará a quien lo\n"
            "instale. Ver docs/FIRMA_DE_CODIGO.md."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
