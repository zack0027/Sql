#!/usr/bin/env bash
# Build the Windows installer. Run from Windows (Git Bash) or a Windows runner.
#
# The Python sidecar is not yet frozen; see ROADMAP.md, Etapa 5. Until then the
# packaged app expects Python on the target machine.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Pruebas antes de empaquetar"
./scripts/test.sh

echo "==> Iconos"
python3 scripts/generate_icons.py >/dev/null

echo "==> Compilando la aplicación"
pnpm --filter @hana/desktop tauri:build

echo
echo "Artefactos en apps/desktop/src-tauri/target/release/bundle/"
