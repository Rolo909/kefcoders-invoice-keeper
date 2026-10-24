#!/bin/sh
# Сквозные тесты веб-панели в контейнере Playwright — на машину ничего ставить не нужно.
# Сначала поднимите стек: docker compose up -d (из корня репозитория).
set -e
cd "$(dirname "$0")"
export MSYS_NO_PATHCONV=1  # Git Bash на Windows: не переписывать пути для docker
HERE="$(pwd -W 2>/dev/null || pwd)"
ADMIN_PASSWORD_FROM_ENV="$(grep '^ADMIN_PASSWORD=' ../.env 2>/dev/null | cut -d= -f2-)"
docker run --rm --ipc=host \
  --add-host=host.docker.internal:host-gateway \
  -e E2E_BASE_URL="${E2E_BASE_URL:-http://host.docker.internal:8080}" \
  -e E2E_ADMIN_PASSWORD="${E2E_ADMIN_PASSWORD:-$ADMIN_PASSWORD_FROM_ENV}" \
  -e E2E_IGNORE_HTTPS_ERRORS \
  -e CI=1 \
  -v "$HERE:/e2e" -v /e2e/node_modules -w /e2e \
  mcr.microsoft.com/playwright:v1.48.2-noble \
  sh -c "npm ci --no-audit --no-fund --loglevel=error && npx playwright test"
