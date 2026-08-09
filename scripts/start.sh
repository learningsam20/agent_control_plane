#!/usr/bin/env bash
# One-click launcher for the Agent Control Plane 2.0.
#
#   ./scripts/start.sh            boot backend (:5186) + workers + frontend (:5185)
#   ./scripts/start.sh datahub    also boot a DataHub quickstart (GMS :8080, UI :9002) first
#   ./scripts/start.sh opa        also start the OPA policy sidecar (:8181)
#   ./scripts/start.sh install    also install Python + npm dependencies first
#   ./scripts/start.sh stop       stop control-plane processes (and DataHub/OPA if started here)
#
# Logs: logs/backend.log, logs/worker.log, logs/frontend.log, logs/datahub.log
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BACKEND_PORT="${PORT:-5186}"
FRONTEND_PORT=5185
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

# 1 when this invocation is asked to launch the corresponding sidecar. Markers
# under logs/ are written only when THIS script launched them, so `stop`/cleanup
# tear them down without killing a pre-existing instance.
DATAHUB_START=0
OPA_START=0
for arg in "${@:-}"; do
  case "$arg" in
    datahub) DATAHUB_START=1 ;;
    opa) OPA_START=1 ;;
  esac
done
DATAHUB_MARKER="$LOG_DIR/datahub.managed"
OPA_MARKER="$LOG_DIR/opa.managed"

pids=()

stop_datahub() {
  [[ -n "${DH_PID:-}" ]] && kill "$DH_PID" 2>/dev/null || true
  if [[ -f "$DATAHUB_MARKER" ]]; then
    echo "[start] stopping DataHub containers (quickstart)"
    datahub docker quickstart --stop > "$LOG_DIR/datahub.log" 2>&1 || true
    rm -f "$DATAHUB_MARKER"
  fi
}

stop_opa() {
  if [[ -f "$OPA_MARKER" ]]; then
    echo "[start] stopping OPA container (opa)"
    docker rm -f opa > /dev/null 2>&1 || true
    rm -f "$OPA_MARKER"
  fi
}

cleanup() {
  echo
  echo "[start] shutting down (backend=$BACKEND_PORT, frontend=$FRONTEND_PORT, worker)"
  stop_datahub
  stop_opa
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  # Belt-and-braces: kill anything still bound to our ports.
  lsof -ti ":$BACKEND_PORT" 2>/dev/null | xargs kill 2>/dev/null || true
  lsof -ti ":$FRONTEND_PORT" 2>/dev/null | xargs kill 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM EXIT

stop_all() {
  lsof -ti ":$BACKEND_PORT" 2>/dev/null | xargs kill 2>/dev/null || true
  lsof -ti ":$FRONTEND_PORT" 2>/dev/null | xargs kill 2>/dev/null || true
  pgrep -f "agents.worker" 2>/dev/null | xargs kill 2>/dev/null || true
  echo "[start] stopped control-plane processes on :$BACKEND_PORT / :$FRONTEND_PORT"
}

if [[ "${1:-}" == "stop" ]]; then
  stop_all
  stop_datahub
  stop_opa
  exit 0
fi

if [[ "${1:-}" == "install" ]]; then
  echo "[start] installing dependencies…"
  python3 -m pip install -q -r backend/requirements.txt
  (cd frontend && npm install --no-audit --no-fund)
fi

# --- DataHub quickstart (optional) ---------------------------------------------
if [[ "$DATAHUB_START" == "1" ]]; then
  if curl -sf "http://localhost:8080/health" > /dev/null 2>&1; then
    echo "[start] DataHub already running on :8080 → skipping quickstart"
  else
    echo "[start] booting DataHub quickstart (GMS :8080, UI :9002)…"
    echo "        first run pulls images and may take several minutes; log: $LOG_DIR/datahub.log"
    datahub docker quickstart > "$LOG_DIR/datahub.log" 2>&1 &
    DH_PID=$!
    echo "$DH_PID" > "$LOG_DIR/datahub.pid"
    : > "$DATAHUB_MARKER"
    DATAHUB_READY=0
    for _ in $(seq 1 300); do
      if curl -sf "http://localhost:8080/health" > /dev/null 2>&1; then
        echo "[start] DataHub ready on :8080 → catalog can sync from DataHub"
        DATAHUB_READY=1
        break
      fi
      if ! kill -0 "$DH_PID" 2>/dev/null; then
        echo "[start] datahub docker quickstart exited early — see $LOG_DIR/datahub.log" >&2
        exit 1
      fi
      sleep 1
    done
    if [[ "$DATAHUB_READY" != "1" ]]; then
      echo "[start] DataHub did not become healthy on :8080 — see $LOG_DIR/datahub.log" >&2
      exit 1
    fi
  fi
fi

# --- OPA policy sidecar (optional) ------------------------------------------------
if [[ "$OPA_START" == "1" ]]; then
  if curl -sf "http://localhost:8181/v1/policies" > /dev/null 2>&1; then
    echo "[start] OPA already running on :8181 → skipping"
  else
    echo "[start] starting OPA policy sidecar (auto engine)…"
    docker run -d --rm --name opa -p 8181:8181 \
      openpolicyagent/opa run --server --addr 0.0.0.0:8181 > "$LOG_DIR/opa.log" 2>&1 || {
        echo "[start] failed to start OPA container — see $LOG_DIR/opa.log" >&2
        exit 1
      }
    : > "$OPA_MARKER"
    OPA_READY=0
    for _ in $(seq 1 30); do
      if curl -sf "http://localhost:8181/v1/policies" > /dev/null 2>&1; then
        echo "[start] OPA ready on :8181 → gateway decisions run through OPA (auto engine)"
        OPA_READY=1
        break
      fi
      sleep 1
    done
    if [[ "$OPA_READY" != "1" ]]; then
      echo "[start] OPA did not become ready on :8181 — see $LOG_DIR/opa.log" >&2
      exit 1
    fi
  fi
fi

# --- backend ---------------------------------------------------------------
echo "[start] booting backend on :$BACKEND_PORT"
(cd backend && exec python3 run.py > "$LOG_DIR/backend.log" 2>&1) &
BACKEND_PID=$!
pids+=("$BACKEND_PID")
echo "$BACKEND_PID" > "$LOG_DIR/backend.pid"
for _ in $(seq 1 60); do
  if curl -sf "http://localhost:$BACKEND_PORT/health" > /dev/null 2>&1; then
    echo "[start] backend ready → http://localhost:$BACKEND_PORT  (docs: /docs)"
    break
  fi
  sleep 0.5
done
if ! curl -sf "http://localhost:$BACKEND_PORT/health" > /dev/null 2>&1; then
  echo "[start] backend failed to become ready — see $LOG_DIR/backend.log" >&2
  exit 1
fi

# --- policy engine probe ------------------------------------------------------
if curl -sf "http://localhost:8181/v1/policies" > /dev/null 2>&1; then
  echo "[start] OPA reachable on :8181 → gateway decisions run through OPA (auto engine)"
else
  echo "[start] OPA not detected on :8181 → using the native policy engine"
  echo "        start it together with the stack: ./scripts/start.sh opa   (:8181)"
fi

# --- DataHub catalog probe -----------------------------------------------------
if curl -sf "http://localhost:8080/health" > /dev/null 2>&1; then
  echo "[start] DataHub reachable on :8080 → catalog can sync from DataHub"
else
  echo "[start] DataHub not detected on :8080 → catalog runs on the bundled reference data"
  echo "        start it together with the stack: ./scripts/start.sh datahub   (GMS :8080, UI :9002)"
fi

# --- agents worker -----------------------------------------------------------
echo "[start] booting agents worker"
(cd backend && exec python3 -u -m agents.worker > "$LOG_DIR/worker.log" 2>&1) &
WORKER_PID=$!
pids+=("$WORKER_PID")
echo "$WORKER_PID" > "$LOG_DIR/worker.pid"

# --- frontend ----------------------------------------------------------------
echo "[start] booting frontend on :$FRONTEND_PORT"
(cd frontend && exec npm run dev > "$LOG_DIR/frontend.log" 2>&1) &
FRONTEND_PID=$!
pids+=("$FRONTEND_PID")
echo "$FRONTEND_PID" > "$LOG_DIR/frontend.pid"
for _ in $(seq 1 60); do
  if curl -sf "http://localhost:$FRONTEND_PORT" > /dev/null 2>&1; then
    echo "[start] frontend ready → http://localhost:$FRONTEND_PORT"
    break
  fi
  sleep 0.5
done

echo
echo "[start] Agent Control Plane 2.0 is up."
echo "        backend   http://localhost:$BACKEND_PORT   (OpenAPI /docs)"
echo "        frontend  http://localhost:$FRONTEND_PORT"
echo "        logs      $LOG_DIR  (tail -f logs/*.log)"
echo "        stop      ./scripts/start.sh stop"
wait
