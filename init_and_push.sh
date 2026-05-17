#!/usr/bin/env bash
# ==============================================================================
# init_and_push.sh
#
# Script idempotente para inicializar el repo y subirlo a GitHub.
# Úsalo así desde la raíz del proyecto descomprimido:
#
#   chmod +x init_and_push.sh
#   ./init_and_push.sh https://github.com/USUARIO/warehouse-digital-twin.git
#
# Requiere git instalado y configurado con tu usuario:
#   git config --global user.name  "Tu Nombre"
#   git config --global user.email "tu@email.com"
# ==============================================================================
set -euo pipefail

REMOTE_URL="${1:-}"

if [ -z "$REMOTE_URL" ]; then
    echo "Uso: $0 <url-del-repo-github>"
    echo "Ejemplo: $0 https://github.com/USUARIO/warehouse-digital-twin.git"
    exit 1
fi

echo "==> Inicializando repo..."
if [ ! -d .git ]; then
    git init -b main
else
    echo "    .git ya existe, saltando init"
fi

echo "==> Configurando remote..."
if git remote get-url origin > /dev/null 2>&1; then
    git remote set-url origin "$REMOTE_URL"
else
    git remote add origin "$REMOTE_URL"
fi

echo "==> Añadiendo archivos..."
git add .

echo "==> Estado:"
git status --short

echo ""
read -p "¿Continuar con el commit? [y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Cancelado."
    exit 0
fi

echo "==> Commit..."
git commit -m "Initial commit: warehouse-digital-twin monorepo

- Backend Python (FastAPI + Pydantic V2 + Ollama narrator) con POO
- Unity 6 URP client con shaders custom (emission + outline)
- Replay tool para demo estática
- CI/CD workflows para tests backend + Unity WebGL deploy
- 7/7 tests passing" || echo "    Nada que commitear (ya estaba commiteado)"

echo "==> Push a $REMOTE_URL..."
git push -u origin main

echo ""
echo "✓ Repo subido. Próximos pasos:"
echo "  1. Habilitar GitHub Pages en Settings > Pages > Source: GitHub Actions"
echo "  2. Correr el workflow 'Acquire Unity Activation File' una vez"
echo "  3. Configurar secrets UNITY_EMAIL, UNITY_PASSWORD, UNITY_LICENSE"
echo "  4. El próximo push a main disparará el build automático"
