#!/usr/bin/env bash
# Run every test suite. Each one is independent of the others' toolchains.
set -euo pipefail
cd "$(dirname "$0")/.."

failed=0

echo "==> Motor (pytest)"
python3 -m pytest engine/tests || failed=1

echo "==> Nativo (cargo test -p jarvis-fs)"
cargo test --manifest-path crates/jarvis-fs/Cargo.toml || failed=1

echo "==> Interfaz (vitest)"
pnpm --filter @jarvis/desktop test || failed=1

echo "==> Tipos (tsc)"
pnpm --filter @jarvis/desktop typecheck || failed=1

if [ "$failed" -ne 0 ]; then
  echo; echo "FALLARON una o más suites."; exit 1
fi
echo; echo "Todo en verde."
