#!/bin/sh
# Runs the control plane container locally.
#
#   ./scripts/docker/run-local.sh [image]
#
# Uses backend/.env for config (LLM_MODEL/LLM_API_KEY, ...) and a persistent
# Docker volume so SQLite survives restarts. OpenRouter example:
#
#   LLM_MODEL=openrouter/anthropic/claude-3.5-sonnet LLM_API_KEY=sk-or-v1-... \
#     ./scripts/docker/run-local.sh
set -e

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

IMAGE="${1:-controlplane:latest}"
PORT="${PORT:-8080}"

if [ ! -f backend/.env ]; then
  echo "backend/.env not found — copying backend/.env.example"
  cp backend/.env.example backend/.env
fi

echo "Running ${IMAGE} on http://localhost:${PORT}"
echo "SQLite + telemetry persist on the 'controlplane-data' Docker volume"
echo "OPA (bundled) evaluates policy on 127.0.0.1:8181 inside the container"
exec docker run --rm -it \
  --name controlplane \
  -p "${PORT}:8080" \
  --env-file backend/.env \
  -e PORT=8080 \
  -e CONTROLPLANE_RUN_WORKER=true \
  -e CONTROLPLANE_POLICY_ENGINE=opa \
  -e CONTROLPLANE_OPA_URL=http://127.0.0.1:8181 \
  -v controlplane-data:/app/backend/data \
  "${IMAGE}"
