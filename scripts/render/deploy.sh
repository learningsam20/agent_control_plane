#!/usr/bin/env bash
# Deploys the control plane to Render as a pre-built Docker image.
#
# The Render CLI (v2) can't create services, so this script drives the
# Render API directly. Flow: build image -> push to Docker Hub -> create the
# service if it doesn't exist -> trigger a deploy -> wait until it goes live.
# Idempotent: re-running after the first deploy just rebuilds and redeploys.
#
# Requires:
#   - Docker (running) with access to the Docker Hub account for the image
#   - RENDER_API_KEY   Render Dashboard > Account Settings > API keys
#   - curl + python3
#
# Optional env:
#   RENDER_OWNER_ID    workspace id (auto-detected from GET /owners if unset)
#   RENDER_REGION      oregon (default) | frankfurt | ohio | singapore | virginia
#   RENDER_PLAN        free (default) | starter | standard | pro | pro_plus | ...
#                      free = no card, but no persistent disk and 15-min idle
#                      spin-down (data lost; app re-seeds on boot)
#   LLM_API_KEY        OpenRouter key; when set, added as an env var
#   LLM_MODEL          default openrouter/anthropic/claude-3.5-sonnet
#   SKIP_BUILD         1 = skip the image build+push (image already on Docker Hub)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

API="https://api.render.com/v1"
IMAGE_NAME="learningsam20/controlplane"
IMAGE_TAG="latest"
IMAGE_PATH="docker.io/${IMAGE_NAME}:${IMAGE_TAG}"
SERVICE_NAME="controlplane"
POLL_ATTEMPTS="${POLL_ATTEMPTS:-60}"

: "${RENDER_API_KEY:?Set RENDER_API_KEY (Render Dashboard > Account Settings > API keys)}"
AUTH="Authorization: Bearer ${RENDER_API_KEY}"

BODYFILE="$(mktemp)"
trap 'rm -f "$BODYFILE"' EXIT

# request METHOD URL [JSON] -> prints HTTP code, body written to $BODYFILE.
# Load the body into $RESP afterwards with resp().
request() {
  local method="$1" url="$2" data="${3:-}"
  local args=(-sS -H "$AUTH" -H "Content-Type: application/json" -X "$method" -o "$BODYFILE" -w "%{http_code}" "$url")
  if [[ -n "$data" ]]; then
    args+=(-d "$data")
  fi
  curl "${args[@]}"
}

resp() { RESP="$(cat "$BODYFILE")"; }

# jget <key path...> reads JSON from stdin and prints the nested value
jget() {
  python3 -c '
import json, sys
try:
    doc = json.load(sys.stdin)
except Exception:
    sys.exit(1)
cur = doc
for part in sys.argv[1:]:
    if isinstance(cur, list):
        try:
            cur = cur[int(part)]
        except (ValueError, IndexError):
            cur = None
    elif isinstance(cur, dict):
        cur = cur.get(part)
    else:
        cur = None
    if cur is None:
        break
if cur is None:
    sys.stdout.write("")
elif isinstance(cur, (dict, list)):
    sys.stdout.write(json.dumps(cur))
else:
    sys.stdout.write(str(cur))
' "$@"
}

echo "==> Building and pushing ${IMAGE_PATH} (linux/amd64 + linux/arm64)"
if [[ "${SKIP_BUILD:-0}" == "1" ]]; then
  echo "    SKIP_BUILD=1 — using existing Docker Hub image"
else
  docker buildx build \
    --platform linux/amd64,linux/arm64 \
    --push \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" .
fi

echo "==> Resolving Render workspace"
OWNER_ID="${RENDER_OWNER_ID:-}"
if [[ -n "$OWNER_ID" ]]; then
  echo "    using RENDER_OWNER_ID=${OWNER_ID}"
else
  code="$(request GET "${API}/owners")"
  resp
  [[ "$code" == "200" ]] || { echo "GET /owners failed ($code): ${RESP}" >&2; exit 1; }
  OWNER_ID="$(echo "$RESP" | jget 0 owner id)"
  OWNER_NAME="$(echo "$RESP" | jget 0 owner name)"
  [[ -n "$OWNER_ID" ]] || { echo "No workspace found. Set RENDER_OWNER_ID." >&2; exit 1; }
  echo "    resolved workspace ${OWNER_NAME} (${OWNER_ID})"
fi

echo "==> Looking for existing service '${SERVICE_NAME}'"
code="$(request GET "${API}/services?name=${SERVICE_NAME}")"
resp
[[ "$code" == "200" ]] || { echo "GET /services failed ($code): ${RESP}" >&2; exit 1; }
SERVICE_ID="$(echo "$RESP" | jget 0 service id)"

if [[ -n "$SERVICE_ID" ]]; then
  echo "    found ${SERVICE_ID}"
  echo "==> Triggering deploy"
  code="$(request POST "${API}/services/${SERVICE_ID}/deploys" '{"clearCache":"do_not_clear"}')"
  resp
  [[ "$code" =~ ^(201|202)$ ]] || { echo "Trigger deploy failed ($code): ${RESP}" >&2; exit 1; }
  DEPLOY_ID="$(echo "$RESP" | jget id)"
else
  echo "    none — creating service"
  ENV_JSON='['
  ENV_JSON+='{"key":"LLM_MODEL","value":"'"${LLM_MODEL:-openrouter/anthropic/claude-3.5-sonnet}"'"},'
  ENV_JSON+='{"key":"CONTROLPLANE_POLICY_ENGINE","value":"opa"},'
  ENV_JSON+='{"key":"CONTROLPLANE_OPA_URL","value":"http://127.0.0.1:8181"},'
  ENV_JSON+='{"key":"CONTROLPLANE_RUN_WORKER","value":"true"},'
  ENV_JSON+='{"key":"CONTROLPLANE_TELEMETRY_EXPORTER","value":"file"},'
  ENV_JSON+='{"key":"SECRET_KEY","generateValue":true}'
  if [[ -n "${LLM_API_KEY:-}" ]]; then
    ENV_JSON+=',{"key":"LLM_API_KEY","value":"'"${LLM_API_KEY}"'"}'
  fi
  ENV_JSON+=']'

  PAYLOAD="$(cat <<JSON
{
  "type": "web_service",
  "name": "${SERVICE_NAME}",
  "ownerId": "${OWNER_ID}",
  "image": {"ownerId": "${OWNER_ID}", "imagePath": "${IMAGE_PATH}"},
  "envVars": ${ENV_JSON},
  "serviceDetails": {
    "runtime": "image",
    "plan": "${RENDER_PLAN:-free}",
    "region": "${RENDER_REGION:-oregon}",
    "numInstances": 1,
    "healthCheckPath": "/health"
$(if [[ "${RENDER_PLAN:-free}" != "free" ]]; then echo '    ,"disk": {"name": "controlplane-data", "mountPath": "/app/backend/data", "sizeGB": 1}'; fi)
  }
}
JSON
)"

  code="$(request POST "${API}/services" "$PAYLOAD")"
  resp
  [[ "$code" =~ ^(201|202)$ ]] || { echo "Create service failed ($code): ${RESP}" >&2; exit 1; }
  SERVICE_ID="$(echo "$RESP" | jget service id)"
  DEPLOY_ID="$(echo "$RESP" | jget deployId)"
  echo "    created ${SERVICE_ID} (deploy ${DEPLOY_ID})"
fi

[[ -n "$DEPLOY_ID" ]] || { echo "No deploy id returned" >&2; exit 1; }

echo "==> Waiting for deploy ${DEPLOY_ID} to go live"
STATUS=""
for i in $(seq 1 "$POLL_ATTEMPTS"); do
  code="$(request GET "${API}/services/${SERVICE_ID}/deploys/${DEPLOY_ID}")"
  resp
  [[ "$code" == "200" ]] || { echo "GET deploy failed ($code): ${RESP}" >&2; exit 1; }
  STATUS="$(echo "$RESP" | jget status)"
  echo "    [$i] status: ${STATUS}"
  case "$STATUS" in
    live) break ;;
    build_failed|update_failed|canceled|pre_deploy_failed|deactivated)
      echo "Deploy failed (${STATUS}). See dashboard for logs." >&2
      exit 1 ;;
  esac
  sleep 10
done

if [[ "$STATUS" != "live" ]]; then
  echo "Timed out waiting for deploy to go live (last status: ${STATUS})." >&2
  exit 1
fi

code="$(request GET "${API}/services/${SERVICE_ID}")"
resp
[[ "$code" == "200" ]] || { echo "GET service failed ($code): ${RESP}" >&2; exit 1; }
URL="$(echo "$RESP" | jget serviceDetails url)"
DASHBOARD="$(echo "$RESP" | jget dashboardUrl)"

echo
echo "Live!"
echo "  URL:       ${URL}"
echo "  Health:    ${URL}/health"
echo "  DataHub:   ${URL}/datahub"
echo "  Dashboard: ${DASHBOARD}"
echo
echo "Next: set LLM_API_KEY in the Dashboard (controlplane > Environment) and redeploy."
