#!/usr/bin/env python3
"""Download the vendored npm tarballs into `vendor/`.

`vendor/` holds four tarballs that `package.json` references with `file:`,
because `registry.npmjs.org` is unreachable from the target network. The
reasoning is in `docs/OFFLINE_DEPENDENCIES.md`. They are 18 MB of third-party
build output, so they are not in the repository — which means a fresh clone
cannot install anything until this script has run.

This is a **build-time** tool. It is never shipped and never imported by the
engine, which still opens no sockets at all; `engine/tests/test_offline.py`
enforces that separately.

What to download is read from `pnpm-lock.yaml`, not from a list kept here.
That matters: the lockfile already records the exact sha512 of every tarball,
so each download is verified against the same hash pnpm will check later.
A corrupted or substituted file fails here, with a message that says so,
instead of surfacing later as an opaque `ERR_PNPM_TARBALL_INTEGRITY`. Adding a
fifth vendored package needs no edit to this file.

Usage:

    python scripts/fetch_vendor.py            # fetch what is missing
    python scripts/fetch_vendor.py --force    # re-download everything
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCKFILE = ROOT / "pnpm-lock.yaml"
VENDOR = ROOT / "vendor"

#: `registry.yarnpkg.com` is npm's own CDN under a second hostname. It serves
#: the same bytes from the same publisher; the only difference is that its name
#: resolves on the target network. Not a third-party mirror, so it does not
#: change who has to be trusted.
REGISTRY = "https://registry.yarnpkg.com"

TIMEOUT_SECONDS = 120

#: A `packages:` key such as `dompurify@file:vendor/dompurify-3.4.12.tgz:`,
#: quoted when the package name is scoped.
_PACKAGE_KEY = re.compile(
    r"^\s{2}'?(?P<name>[^'\s]+?)@file:vendor/(?P<filename>[^'\s]+?\.tgz)'?:\s*$"
)

_INTEGRITY = re.compile(r"integrity:\s*(?P<integrity>sha\d+-[A-Za-z0-9+/=]+)")

#: The version at the tail of a tarball name: `marked-18.0.7.tgz` → `18.0.7`.
_VERSION = re.compile(r"-(?P<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\.tgz$")


@dataclass(frozen=True)
class Package:
    name: str
    filename: str
    integrity: str

    @property
    def version(self) -> str:
        match = _VERSION.search(self.filename)
        if match is None:
            raise ValueError(
                f"no se puede deducir la versión de «{self.filename}»; "
                "se esperaba un nombre como paquete-1.2.3.tgz"
            )
        return match.group("version")

    @property
    def url(self) -> str:
        # The last path segment always uses the *unscoped* name, which is why
        # it is rebuilt rather than reusing `filename`: the local copy of
        # `@types/trusted-types` is stored as `types-trusted-types-2.0.7.tgz`
        # to keep `vendor/` flat, and that name does not exist in the registry.
        unscoped = self.name.rsplit("/", 1)[-1]
        return f"{REGISTRY}/{self.name}/-/{unscoped}-{self.version}.tgz"

    @property
    def destination(self) -> Path:
        return VENDOR / self.filename

    def matches(self, data: bytes) -> bool:
        algorithm, _, expected = self.integrity.partition("-")
        digest = hashlib.new(algorithm, data).digest()
        return base64.b64encode(digest).decode("ascii") == expected


def vendored_packages(lockfile: Path) -> list[Package]:
    """Every `file:vendor/…` dependency the lockfile pins, with its hash."""
    lines = lockfile.read_text(encoding="utf-8").splitlines()
    packages: list[Package] = []
    seen: set[str] = set()

    for index, line in enumerate(lines):
        key = _PACKAGE_KEY.match(line)
        if key is None:
            continue
        # The `snapshots:` section repeats the same keys without a resolution.
        following = lines[index + 1] if index + 1 < len(lines) else ""
        integrity = _INTEGRITY.search(following)
        if integrity is None:
            continue
        filename = key.group("filename")
        if filename in seen:
            continue
        seen.add(filename)
        packages.append(
            Package(
                name=key.group("name"),
                filename=filename,
                integrity=integrity.group("integrity"),
            )
        )
    return packages


def fetch(package: Package, *, force: bool) -> str:
    """Ensure the tarball is on disk and correct. Returns what was done."""
    destination = package.destination
    if destination.exists() and not force:
        if package.matches(destination.read_bytes()):
            return "ya estaba"
        # A file that is there but wrong is worse than one that is missing:
        # left alone it would fail much later, in pnpm, with a worse message.
        print(f"    hash incorrecto, se vuelve a descargar: {package.filename}")

    try:
        with urllib.request.urlopen(package.url, timeout=TIMEOUT_SECONDS) as response:
            data = response.read()
    except urllib.error.URLError as error:
        raise SystemExit(
            f"no se pudo descargar {package.url}\n"
            f"  motivo: {error}\n"
            f"  Si esta red tampoco alcanza registry.yarnpkg.com, copia la\n"
            f"  carpeta vendor/ desde un equipo que sí la tenga."
        ) from error

    if not package.matches(data):
        raise SystemExit(
            f"lo descargado de {package.url} no coincide con el hash del\n"
            f"  lockfile ({package.integrity}). No se guarda."
        )

    VENDOR.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return f"descargado ({len(data) // 1024} KB)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="volver a descargar aunque el archivo ya esté y sea correcto",
    )
    arguments = parser.parse_args()

    if not LOCKFILE.exists():
        raise SystemExit(f"no existe {LOCKFILE}")

    packages = vendored_packages(LOCKFILE)
    if not packages:
        print("El lockfile no referencia ningún paquete en vendor/. Nada que hacer.")
        return 0

    print(f"Paquetes vendorizados según {LOCKFILE.name}: {len(packages)}")
    for package in packages:
        outcome = fetch(package, force=arguments.force)
        print(f"  {package.name:26} {package.version:10} {outcome}")

    print(f"\nListo. vendor/ está completo y verificado en {VENDOR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
