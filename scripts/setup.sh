#!/usr/bin/env bash
# Prepare a development checkout. Idempotent.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Comprobando herramientas"
for tool in node pnpm python3 cargo; do
  command -v "$tool" >/dev/null || { echo "falta: $tool"; exit 1; }
  printf '    %-8s %s\n' "$tool" "$($tool --version | head -1)"
done

echo "==> Instalando dependencias de la interfaz"
pnpm install

echo "==> Instalando el motor en modo editable"
python3 -m pip install -e "engine[dev]"

echo "==> Generando iconos"
python3 scripts/generate_icons.py >/dev/null

echo
echo "Listo. Siguientes pasos:"
echo "  pnpm tauri:dev     aplicación de escritorio completa"
echo "  pnpm dev           solo la interfaz (motor simulado)"
echo "  ./scripts/test.sh  las tres suites de pruebas"
