# Setup

How to stand up **Agent Control Plane 2.0** from scratch — the same app this
repository produces — by following this guide top to bottom. No cloud
credentials are required; the whole stack runs locally and offline. The first
backend boot auto-seeds demo agents, policies, and a reference data catalog, so
every screen is populated out of the box.

When you finish you'll have:

| Component | What it is | URL |
| --------- | ---------- | --- |
| **Console** | React (Vite) UI — every page in this app | http://localhost:5185 |
| **Backend** | FastAPI + SQLite control plane (policy gateway, audit chain, DataHub catalog API) | http://localhost:5186 |
| **Agent worker** | Runs governed agent objectives (LangGraph) | `:5186` API · polls runs |
| **OPA** *(optional)* | Policy engine that evaluates gateway decisions — bundled *inside* the Docker images, or run as a sidecar for local dev | http://localhost:8181 |
| **DataHub** *(optional)* | DataHub quickstart that feeds the catalog + lineage | GMS :8080 · UI :9002 |

---

## 1 · Prerequisites

| Tool | Version | Needed for |
| ---- | ------- | ---------- |
| **Python** | 3.10+ (tested on 3.14) with `pip` | Backend, agent worker, scripts |
| **Node.js** | 18+ with `npm` | Frontend console |
| **Docker** | Recent (Docker Desktop or compatible) | Container images; OPA sidecar + DataHub quickstart are optional |
| **DataHub CLI** *(optional)* | Latest `acryl-datahub` | `./scripts/start.sh datahub` — see below |

> macOS and Linux are fully supported. On Windows use **WSL2** and run the same
> commands inside the Ubuntu distribution.

> The full **DataHub stack** (JVM GMS + OpenSearch + Kafka + MySQL) needs
> roughly **8 GB of RAM** and a couple of GB of disk. OPA is lightweight
> (~30 MB static binary) and runs inside the container with no extra RAM to
> budget for.

If you want the DataHub-backed catalog, install the CLI that the quickstart
launcher calls (`datahub docker quickstart`):

```bash
python3 -m pip install --upgrade acryl-datahub
datahub version        # verify it's on PATH
```

---

## 2 · Get the code

```bash
git clone <this-repository> datahub
cd datahub
```

The repository is laid out as:

```text
backend/         FastAPI control plane (app/), governed agents (agents/), tests/
frontend/        React + Vite + TypeScript console
scripts/         start.sh (one-click launcher) and demo.py (scripted demo)
examples/        01–06 numbered scenario scripts
policies/        datahub.rego — the Rego module pushed to OPA
ARCHITECTURE.md  deep-dive on how the pieces fit together
```

---

## 3 · Install dependencies

One command installs the backend Python requirements and the frontend npm
packages:

```bash
./scripts/start.sh install
```

Or install each side manually:

```bash
# backend
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows (WSL): source .venv/bin/activate
pip install -r requirements.txt

# frontend
cd ../frontend
npm install
```

> Use `npm install` (not a global install); the console's dependencies are
> pinned in `frontend/package-lock.json`.

---

## 4 · (Optional) Sidecars — OPA and DataHub

Neither is required. The backend's policy engine defaults to `auto`, which uses
OPA when it's reachable and transparently falls back to a built-in native
engine. The DataHub catalog likewise runs on bundled reference data when no
DataHub is detected. Skip this section and the stack still works — add the
sidecars later anytime with `./scripts/start.sh datahub opa`.

> When running via the **Docker images** (§12), skip the OPA sidecar below —
> OPA is bundled inside the image and started automatically on
> `127.0.0.1:8181`. This section only applies to bare-metal local dev.

### OPA policy sidecar

```bash
docker run -d --rm --name opa -p 8181:8181 \
  openpolicyagent/opa run --server --addr 0.0.0.0:8181
```

At startup the control plane pushes `policies/datahub.rego` (package
`controlplane`) to OPA and evaluates every gateway request there — look for
`[control-plane] OPA reachable …` in the backend log. Stop the container to
revert to the native engine transparently:

```bash
docker stop opa
```

> `--addr 0.0.0.0:8181` is required so the published port is reachable from the
> host (binding to `localhost` inside the container is IPv6-only and not
> forwarded by Docker Desktop).

### DataHub quickstart

```bash
datahub docker quickstart          # first run pulls images; can take minutes
datahub docker check               # GMS healthy on :8080?
```

DataHub's UI lands on http://localhost:9002 and GMS on :8080. Once it's up, the
console's **DataHub** page can sync the catalog from it. Live DataHub is
optional — leave `DATAHUB_ENDPOINT` unset to keep using the bundled reference
catalog.

---

## 5 · Boot the stack

### One-click launcher (recommended)

```bash
./scripts/start.sh datahub opa      # boot DataHub + OPA first, then the stack
```

Run just `./scripts/start.sh` if you skipped the sidecars (or they're already
running). The launcher writes logs to `logs/` and waits for each service to
become healthy before moving on:

```bash
./scripts/start.sh                  # backend :5186 + agent worker + frontend :5185
./scripts/start.sh stop             # stop everything it started
```

### Manual start

Use three terminals (or run the backend + worker in the same venv):

```bash
# terminal 1 — backend
cd backend
source .venv/bin/activate
cp .env.example .env                # optional overrides
python3 run.py                      # http://localhost:5186

# terminal 2 — agent worker
cd backend
source .venv/bin/activate
python3 -u -m agents.worker         # interval/name via WORKER_POLL_INTERVAL / WORKER_NAME

# terminal 3 — frontend
cd frontend
npm run dev                         # http://localhost:5185 (proxies /api → :5186)
```

---

## 6 · Verify it works

1. Open **http://localhost:5185** — you should see the console sidebar.
2. Backend health: `curl http://localhost:5186/health` → `{"status":"ok", …}`.
3. OpenAPI docs: http://localhost:5186/docs.
4. First boot seeds the DB automatically, so **Agents**, **Policies**,
   **Delegations**, **DataHub**, and **Audit Trail** are already populated —
   no manual seeding step.
5. Run the six scripted scenarios for an end-to-end sanity check:

```bash
python3 scripts/demo.py
```

Which exercises onboarding → signed policy requests → delegation → tamper
verification → DataHub impact → governed agent runs.

| URL | What you should see |
| --- | ------------------- |
| http://localhost:5185 | React console (login-free) |
| http://localhost:5186/docs | Swagger UI for every API |
| http://localhost:5186/health | `{"status":"ok"}` |

---

## 7 · Configuration

All configuration flows through `backend/app/config.py` (pydantic-settings),
read from environment variables or `backend/.env`:

```bash
cp backend/.env.example backend/.env
```

Key knobs — see `backend/.env.example` and [ARCHITECTURE.md](ARCHITECTURE.md#configuration) for the full table:

- `HOST`, `PORT`, `SELF_URL`, `CONTROLPLANE_URL` — networking.
- `DATABASE_URL` — SQLite by default.
- `LLM_MODEL` — set to a LiteLLM model id (e.g. `openai/gpt-4o-mini`,
  `ollama/llama3.2`) to use the LLM planner; leave empty for the built-in
  rule-based planner (offline default).
- `CONTROLPLANE_TELEMETRY_EXPORTER` — `file` (default) | `otlp` | `console` | `none`.
- `CONTROLPLANE_POLICY_ENGINE` — `auto` | `native` | `opa` (see [OPA](#opa-policy-sidecar)).
- `CONTROLPLANE_OPA_URL`, `CONTROLPLANE_OPA_POLICY_FILE` — OPA endpoint + Rego module to push.
- `DATAHUB_ENDPOINT`, `DATAHUB_TOKEN` — live DataHub GMS endpoint (GraphQL reads
  + MetadataChangeProposal writes); leave unset for the bundled reference catalog.
- `USE_DATAHUB_MCP` — `true` routes catalog/lineage reads through the
  `@acryldata/mcp-server-datahub` MCP server, with GraphQL fallback; default `false`.
- `USE_ANALYTICS_AGENT` — `true` answers `POST /api/datahub/analytics` via a
  `datahub-analytics-agent`; default `false`.

> Frontend config lives in `frontend/vite.config.ts` (ports + `/api` proxy
> target). Set `CONTROLPLANE_API_URL` there to target a remote control plane.

---

## 8 · The scripted demo, step by step

`scripts/demo.py` wipes the database, boots the API, and runs all six examples:

```bash
python3 scripts/demo.py
```

| Script | Scenario | Outcome you should see |
| ------ | -------- | ---------------------- |
| `examples/01_onboard_agents.py` | Register three agents with Ed25519 identities | 3 agents registered, keys written to `backend/data/agents/` |
| `examples/02_policy_requests.py` | Signed read/query/transform requests | In-scope reads allowed; restricted finance denied |
| `examples/03_delegation_flow.py` | Scoped delegation chain | Delegated read allowed; out-of-scope write denied |
| `examples/04_verify_chain.py` | Tamper simulation | `verify_chain` flags the altered block |
| `examples/05_datahub_impact.py` | Agent × dataset impact | Catalog + impact heatmap data written |
| `examples/06_langgraph_agent.py` | Governed LangGraph agent runs | Objective → plan → governed actions → audit trail |

Run any example individually against a fresh server:

```bash
python3 examples/01_onboard_agents.py      # needs the API on :5186
```

### Interactive console flows

1. **Zero-Trust Lab** — one click runs the six-step trust scenario:
   baseline read **allowed** → restricted finance read **denied** → reputation
   gating → scoped delegation issued → delegated read **allowed** →
   out-of-scope write **denied**. Watch tier/score update live.
2. **Agent Runs** — type a natural-language objective for an agent, submit, and
   watch the plan execute through the gateway (async runs handled by the worker).
3. **Audit Trail** — inspect every signed event, then **Simulate tamper** and
   watch chain verification flag it.

---

## 9 · Telemetry (MELT)

Run a few actions (demo or console), then inspect the sinks:

```bash
ls backend/data/telemetry/        # metrics.jsonl  traces.jsonl  logs.jsonl
python3 -c "import json;print(sorted({json.loads(l)['name'] for l in open('backend/data/telemetry/traces.jsonl') if l.strip()}))"
```

| Signal | File | Example |
| ------ | ---- | ------- |
| Metrics | `metrics.jsonl` | `gateway.decisions`, `agents.runs` |
| Events | `logs.jsonl` | `request.query`, `request.query.denied`, `agent.run.*` |
| Logs | `logs.jsonl` | `worker started` (structured records) |
| Traces | `traces.jsonl` | `agents.plan`, `agents.execute`, `agents.query` |

Point a collector anywhere with `CONTROLPLANE_TELEMETRY_EXPORTER=otlp` and
`OTEL_EXPORTER_OTLP_ENDPOINT=http://<collector>:4318`.

---

## 10 · Tests

```bash
cd backend && python3 -m pytest -q     # gateway, delegation, runs, chain, planner, config, OPA adapter, DataHub monitor/impact/watchlist, MCP/analytics gating
cd frontend && npm run build           # type-check + production build
```

The OPA tests (`tests/test_opa.py`) exercise the Rego input mapping, verbatim
policy push, and decision parsing against a stubbed HTTP layer; with a live OPA
on `:8181` the full `test_governed_agent_run` also routes through OPA.

---

## 11 · Troubleshooting

| Symptom | Fix |
| ------- | --- |
| Backend not healthy at `:5186` | `tail logs/backend.log`; confirm nothing else is on the port |
| Worker never picks up runs | Start it: `cd backend && python3 -u -m agents.worker`; check `logs/worker.log` |
| Signature failures after a DB wipe | Demo keys live in `backend/data/demo_agents/` and persist across wipes; `POST /api/demo/reset` restores agents |
| `datahub: command not found` | `pip install --upgrade acryl-datahub` (only needed for the optional DataHub quickstart) |
| DataHub quickstart hangs | First run pulls images — give it several minutes; watch `logs/datahub.log` |
| Port already in use | `lsof -ti :5185 :5186 :8181 :8080` and kill, or change `PORT`/vite port |
| LLM planner not used | Set `LLM_MODEL` (+ `LLM_BASE_URL`/`LLM_API_KEY`) in `backend/.env`; otherwise the rule-based planner runs |
| OPA not used (engine shows `native`) | Confirm OPA is up (`curl :8181/v1/policies`) and started with `--addr 0.0.0.0:8181`; watch for the `[control-plane] OPA reachable …` startup line |

---

## 12 · Deploy with Docker

Everything above is also packaged as **one self-contained Docker image**: the
React console is built and served from the same FastAPI process (no separate
frontend server), agent runs execute in-process, and the SQLite database +
telemetry live in `/app/backend/data`. **OPA is bundled inside the image** —
the entrypoint starts it on `127.0.0.1:8181` and the backend pushes
`policies/datahub.rego` at startup, so policy evaluation runs through the real
Rego engine with no sidecar. Only **DataHub** lives outside the image, as a
separate compose stack (see below).

Two images are produced by `./scripts/docker/build.sh`:

| Image | Dockerfile | Use for |
| ----- | ---------- | ------- |
| `controlplane:latest` | `Dockerfile` | Local runs + **Render** (persistent host, runs the worker too) |
| `controlplane:vercel` | `Dockerfile.vercel` | **Vercel** (stateless, no background worker — console runs are sync) |

**OpenRouter for LLM calls:** set these two env vars instead of Ollama —
no code changes:

```bash
LLM_MODEL=openrouter/anthropic/claude-3.5-sonnet
LLM_API_KEY=sk-or-v1-...       # https://openrouter.ai/keys
```

Swap the model id freely (`openrouter/openai/gpt-4o-mini`, etc.). Leave
`LLM_MODEL` empty and the rule-based planner runs with no external dependency.

### Local (Docker)

```bash
./scripts/docker/build.sh                  # build both images (first run is slow)
./scripts/docker/run-local.sh              # http://localhost:8080
```

`run-local.sh` reads `backend/.env` for config (copy `backend/.env.example`
first and set `LLM_MODEL`/`LLM_API_KEY`) and mounts a persistent Docker volume
so the database survives restarts. It runs the **worker too**, so the full
async agent-run queue works.

```bash
docker stop controlplane   # stop; data stays on the controlplane-data volume
```

### Full platform with DataHub (Docker Compose)

One command brings up **everything** — the control plane (with OPA inside) plus
the real DataHub stack — as a single compose project:

```bash
./scripts/docker/stack.sh up       # docker compose up -d --build
```

| URL | What it is |
| --- | ---------- |
| http://localhost:8080 | Console + API (controlplane service) |
| http://localhost:9002 | DataHub UI (frontend-quickstart) |
| http://localhost:18080 | DataHub GMS (remapped so it doesn't clash with the console's :8080) |

The stack is defined by `docker-compose.yml` at the repo root, which `include`s
the vendored DataHub stack in `deploy/datahub/docker-compose.datahub.yml`
(upstream quickstart, pinned to `DATAHUB_VERSION=v1.7.0` — set in the root
`.env`). Services: `mysql` (store), `opensearch` (search), `kafka-broker`
(KRaft, no zookeeper), `datahub-gms`, `datahub-actions`, `system-update`
(first-boot migrations), `frontend-quickstart`. The control plane connects
automatically via `DATAHUB_ENDPOINT=http://datahub-gms:8080` and the **DataHub**
page in the console switches from the reference catalog to the live DataHub
graph.

```bash
./scripts/docker/stack.sh logs     # follow all logs
./scripts/docker/stack.sh ps       # service status
./scripts/docker/stack.sh down     # stop; add -v to also drop DataHub volumes
```

> **Resource note:** DataHub needs ~8 GB of RAM (JVM GMS + OpenSearch + Kafka +
> MySQL). Give Docker Desktop at least 8 GB. On low-memory machines, skip
> DataHub and use `run-local.sh` instead.

### Render (recommended for hosting)

Render runs the **same persistent image** (`controlplane:latest`) as a web
service. The bundled worker runs continuously, giving you the full async
agent-run queue. OPA runs **inside** the container on `127.0.0.1:8181`
(`CONTROLPLANE_POLICY_ENGINE=opa`), so policy evaluation uses the Rego engine
with no sidecar.

The Render CLI (v2) can't create services, so deployment is driven by the
Render API through `scripts/render/deploy.sh`: it builds and pushes a
**multi-arch** (`linux/amd64` + `linux/arm64`) image to Docker Hub with
`docker buildx`, then creates the service (if absent), sets env vars, triggers
a deploy, and polls until it's live.

```bash
RENDER_API_KEY='rnd_...' LLM_API_KEY='sk-or-v1-...' \
  ./scripts/render/deploy.sh          # build+push+create+deploy
SKIP_BUILD=1 ./scripts/render/deploy.sh   # skip rebuild, redeploy the pushed image
```

Optional env: `RENDER_PLAN` (`free` default | `starter` …), `RENDER_REGION`
(`oregon` default), `RENDER_OWNER_ID` (auto-detected), `SKIP_BUILD=1`,
`POLL_ATTEMPTS`. The API key comes from
**https://dashboard.render.com/u/settings?add-api-key** → Account Settings →
API Keys → Create (shown in full exactly once).

**Plans and caveats:**

- `free` (default) needs **no card** but supports **no persistent disk** and
  spins down after ~15 min of idle traffic (cold start ~1 min on the next
  request). The SQLite DB + telemetry reseed from the bundled reference catalog
  on each boot — fine for a demo.
- `starter` (paid) attaches the 1 GB `controlplane-data` disk at
  `/app/backend/data` so state survives restarts and redeploys.
- The console shows a **Reference catalog mode** badge because DataHub isn't
  part of the Render service (its ~8 GB stack doesn't fit small plans). To sync
  from a live DataHub, add `DATAHUB_ENDPOINT` (and `DATAHUB_TOKEN`) pointing at
  a GMS you run elsewhere — e.g. a host running `./scripts/docker/stack.sh`.
  Everything else is pre-configured; the service URL is the app:
  `https://<service>.onrender.com` (console + API in one place).

### Vercel (shareable demo)

Vercel deploys the **stateless** `Dockerfile.vercel` image on Fluid compute.
Because Vercel containers have no persistent disk and no background worker,
SQLite reseeds demo data per instance and only synchronous runs are available —
fine for a shareable demo, not for state you need to keep. OPA is bundled in
the image too, so policy evaluation still uses the Rego engine. DataHub is not
part of this image (ephemeral stack would not survive anyway); the console uses
the bundled reference catalog.

```bash
npm install -g vercel && vercel login
vercel env add LLM_MODEL production        # openrouter/anthropic/claude-3.5-sonnet
vercel env add LLM_API_KEY production      # sk-or-v1-...
vercel env add CONTROLPLANE_POLICY_ENGINE production   # opa
vercel env add CONTROLPLANE_OPA_URL production         # http://127.0.0.1:8181
vercel env add SECRET_KEY production
./scripts/vercel/deploy.sh                 # or: vercel --prod
```

Every `git push` rebuilds the image and gets a fresh preview URL; `vercel
--prod` promotes to the production `*.vercel.app` domain.
