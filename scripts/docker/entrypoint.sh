#!/bin/sh
# Container entrypoint (shared by Dockerfile and Dockerfile.vercel).
#
# - Starts the bundled OPA engine on 127.0.0.1:8181 and waits until it is
#   ready; the backend pushes policies/datahub.rego at startup.
# - Listens on $PORT (Render/Vercel/containers set it; default 8080).
# - Defaults SELF_URL to loopback so the bundled worker polls this container
#   directly without needing a public URL.
# - Runs the agent worker alongside the API unless CONTROLPLANE_RUN_WORKER=false
#   (the Vercel image ships with it disabled).
set -e

PORT="${PORT:-8080}"
export PORT
export SELF_URL="${SELF_URL:-http://127.0.0.1:${PORT}}"
export CONTROLPLANE_OPA_URL="${CONTROLPLANE_OPA_URL:-http://127.0.0.1:8181}"
export CONTROLPLANE_POLICY_ENGINE="${CONTROLPLANE_POLICY_ENGINE:-opa}"

if [ -x /usr/local/bin/opa ]; then
  opa run --server --addr 127.0.0.1:8181 >/dev/null 2>&1 &
  OPA_PID=$!
  echo "[entrypoint] opa pid ${OPA_PID} on :8181"
  n=0
  until python3 -c "import urllib.request; urllib.request.urlopen('${CONTROLPLANE_OPA_URL}/v1/policies', timeout=1)" >/dev/null 2>&1 || [ "$n" -ge 30 ]; do
    n=$((n + 1)); sleep 0.5
  done
  if [ "$n" -ge 30 ]; then
    echo "[entrypoint] WARNING: OPA did not become ready within 15s"
  else
    echo "[entrypoint] OPA ready after ~$((n / 2))s"
  fi
else
  echo "[entrypoint] opa binary not present — using native engine"
  export CONTROLPLANE_POLICY_ENGINE="${CONTROLPLANE_POLICY_ENGINE:-native}"
fi

uvicorn app.main:app --host 0.0.0.0 --port "$PORT" &
API_PID=$!
echo "[entrypoint] api pid ${API_PID} on :${PORT}"

WORKER_PID=""
if [ "${CONTROLPLANE_RUN_WORKER:-true}" = "true" ]; then
  python3 -u -m agents.worker &
  WORKER_PID=$!
  echo "[entrypoint] worker pid ${WORKER_PID} polling ${SELF_URL}"
fi

cleanup() {
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null || true
  [ -n "$WORKER_PID" ] && kill "$WORKER_PID" 2>/dev/null || true
  [ -n "$OPA_PID" ] && kill "$OPA_PID" 2>/dev/null || true
  exit 0
}
trap 'cleanup' TERM INT

wait "$API_PID"
