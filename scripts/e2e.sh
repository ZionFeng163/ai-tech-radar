#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_NAME="${E2E_PROJECT_NAME:-ai-tech-radar-e2e}"
export POSTGRES_PORT="${E2E_POSTGRES_PORT:-15432}"
export REDIS_PORT="${E2E_REDIS_PORT:-16379}"
export BACKEND_PORT="${E2E_BACKEND_PORT:-18000}"
export FRONTEND_PORT="${E2E_FRONTEND_PORT:-13000}"
export E2E_BACKEND_URL="http://localhost:${BACKEND_PORT}"
export E2E_FRONTEND_URL="http://localhost:${FRONTEND_PORT}"

cleanup() {
  status=$?
  if [[ $status -ne 0 ]]; then
    echo "[e2e] services failed; recent logs follow" >&2
    docker compose -p "$PROJECT_NAME" logs --no-color --tail=120 backend frontend >&2 || true
  fi
  docker compose -p "$PROJECT_NAME" down --volumes --remove-orphans >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT

echo "[e2e] starting isolated Docker stack"
docker compose -p "$PROJECT_NAME" up -d --build --wait postgres redis backend frontend

echo "[e2e] applying database migrations"
docker compose -p "$PROJECT_NAME" exec -T backend alembic upgrade head

echo "[e2e] inserting deterministic sample data"
docker compose -p "$PROJECT_NAME" exec -T backend python scripts/seed_e2e.py
docker compose -p "$PROJECT_NAME" exec -T backend python scripts/seed_e2e.py

echo "[e2e] verifying API and Web routes"
python3 backend/scripts/verify_e2e.py
