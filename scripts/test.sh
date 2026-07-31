#!/usr/bin/env bash
# Run every test suite. Each one is independent of the others' toolchains.
set -euo pipefail
cd "$(dirname "$0")/.."

failed=0

# On Windows `python3` is a Microsoft Store alias that refuses to run, so asking
# for it by name turns an absence into a reported test failure — and this script
# is the gate for calling anything finished. Take whichever name answers.
python_bin=""
for candidate in python3 python py; do
  if "$candidate" -c "" >/dev/null 2>&1; then
    python_bin="$candidate"
    break
  fi
done
if [ -z "$python_bin" ]; then
  echo "no se encontró un intérprete de Python (probados: python3, python, py)"
  exit 1
fi

echo "==> Motor (pytest, con $python_bin)"
"$python_bin" -m pytest engine/tests || failed=1

echo "==> Nativo (cargo test -p hana-fs)"
cargo test --manifest-path crates/hana-fs/Cargo.toml || failed=1

echo "==> Interfaz (vitest)"
pnpm --filter @hana/desktop test || failed=1

echo "==> Tipos (tsc)"
pnpm --filter @hana/desktop typecheck || failed=1

if [ "$failed" -ne 0 ]; then
  echo; echo "FALLARON una o más suites."; exit 1
fi
echo; echo "Todo en verde."
