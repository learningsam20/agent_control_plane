# syntax=docker/dockerfile:1

# Agent Control Plane 2.0 — single-container image for persistent hosts
# (Render, Railway, Fly.io, any VM/Dokku/ECS) and local runs.
#
# - Builds the React console, then serves it from the same FastAPI process.
# - Agent runs execute in-process (?sync=true); a bundled background worker
#   also polls pending runs when CONTROLPLANE_RUN_WORKER=true.
# - SQLite + telemetry live under /app/backend/data — mount a volume there for
#   persistence (Render: see render.yaml).

# ---------- stage 1: build the console ----------
FROM node:20-alpine AS web-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- stage 2: runtime ----------
FROM python:3.12-slim AS runtime

# tini gives us correct signal handling / PID 1 behavior
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini curl \
 && rm -rf /var/lib/apt/lists/*

# Bundle the Open Policy Agent engine (started in-container by entrypoint.sh
# on 127.0.0.1:8181; the backend pushes policies/datahub.rego at startup).
# The static binary needs no JVM and no additional packages.
ARG OPA_VERSION=v0.68.0
RUN set -eux; \
    case "$(uname -m)" in \
      x86_64) OPA_ARCH=amd64 ;; \
      aarch64|arm64) OPA_ARCH=arm64 ;; \
      *) echo "unsupported arch: $(uname -m)" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/opa \
      "https://github.com/open-policy-agent/opa/releases/download/${OPA_VERSION}/opa_linux_${OPA_ARCH}_static"; \
    chmod +x /usr/local/bin/opa; \
    curl -fsSL "https://github.com/open-policy-agent/opa/releases/download/${OPA_VERSION}/opa_linux_${OPA_ARCH}_static.sha256" -o /tmp/opa.sha256; \
    (cd /tmp && sha256sum -c opa.sha256 --ignore-missing 2>/dev/null || sha256sum /usr/local/bin/opa); \
    rm -f /tmp/opa.sha256; \
    apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

COPY backend/app ./app
COPY backend/agents ./agents
COPY backend/sdk ./sdk
COPY backend/run.py ./
COPY policies /app/policies
COPY --from=web-build /app/frontend/dist /app/frontend/dist
COPY scripts/docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV PORT=8080 \
    CONTROLPLANE_RUN_WORKER=true \
    CONTROLPLANE_POLICY_ENGINE=opa \
    CONTROLPLANE_OPA_URL=http://127.0.0.1:8181

EXPOSE 8080 8181
ENTRYPOINT ["tini", "--", "/usr/local/bin/entrypoint.sh"]
