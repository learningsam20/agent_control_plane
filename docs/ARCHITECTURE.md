# Agent Control Plane — Architecture

Governed LangGraph agents, a signed zero-trust gateway, tamper-evident audit,
reputation, and DataHub context — with vendor-neutral MELT telemetry. Ships as
a single self-contained Docker image (console + API + bundled OPA + agent
worker) that runs anywhere: local, Render, Vercel, or a plain VM.

## System overview

```mermaid
flowchart LR
    subgraph Console[React console :5185 / :8080 in container]
        UI[Dashboard / Agents / Runs / Zero-Trust Lab / Audit / Policies / DataHub / Lineage / Monitor / Impact]
        BADGE[Badge: Live DataHub catalog<br/>vs Reference catalog mode]
    end

    subgraph CP[Control plane :5186]
        API[FastAPI /api]
        GW[Policy gateway evaluate_signed]
        POL[Policy engine<br/>native + OPA fallback]
        REP[Reputation engine]
        DEL[Delegation + scope checks]
        HC[Hash-chain audit]
        CAT[DataHub catalog<br/>live GMS + bundled reference]
        CRIT[Criticality & monitor<br/>watchlist + guardian scans]
        IMP[Impact analysis<br/>blast radius · what-if]
        MET[OTel traces/metrics/events/logs]
    end

    subgraph RT[Agent runtime]
        WORKER[agents worker]
        LANG[LangGraph<br/>planner → executor → summarizer]
        KEYS[(Ed25519 private keys<br/>data/demo_agents)]
        TOOLS[GovernedToolSet]
    end

    subgraph OUT[Observability]
        FILE[JSONL files<br/>data/telemetry/*.jsonl]
        OTLP[OTLP collector<br/>Tempo / Jaeger / Loki / …]
    end

    REF[(Reference catalog<br/>bundled seed data)]
    SDK[Python SDK<br/>sdk/controlplane.py]
    DH[DataHub GMS<br/>GraphQL reads +<br/>MetadataChangeProposal writes<br/>when DATAHUB_ENDPOINT set]
    MCP[DataHub MCP server<br/>optional when USE_DATAHUB_MCP=true]

    UI -->|proxy /api| API
    UI --> BADGE
    BADGE -. status endpoint .-> CAT
    SDK -->|Ed25519 signed envelope| API
    WORKER -->|claims /api/runs/pending| API
    WORKER --> LANG
    LANG --> TOOLS
    KEYS --> WORKER
    TOOLS -->|signed requests| GW
    API --> GW
    GW --> POL
    GW --> REP
    GW --> DEL
    GW --> HC
    GW --> CAT
    CAT --> DH
    REF -. no DATAHUB_ENDPOINT .-> CAT
    CAT -. USE_DATAHUB_MCP .-> MCP
    MCP -. fallback to DH .-> DH
    CAT --> CRIT
    CRIT --> HC
    IMP --> CAT
    IMP --> HC
    API --> MET
    LANG --> MET
    MET --> FILE
    MET --> OTLP
```

## Trust model — zero trust, end to end

There is no shared secret and no implicit trust. Every request is an **Ed25519
signed envelope**:

```mermaid
sequenceDiagram
    participant A as Agent (worker/SDK)
    participant CP as Control plane
    participant P as Policy engine
    participant H as Audit hash-chain
    participant D as DataHub catalog

    A->>A: canonical_json(body)
    A->>A: signature = sign(private_key, body)
    A->>CP: POST /api/requests/gateway (body + X-Agent-Signature)
    CP->>CP: verify(public_key, signature, body)
    CP->>CP: resolve reputation tier
    CP->>P: evaluate(action, resource, domains, delegation)
    alt allow
        P-->>CP: allow (policy_name)
        CP->>H: append request.{action} (signed)
        CP->>D: read catalog metadata / write impact
        CP-->>A: {decision: allow, result}
    else deny
        P-->>CP: deny (default-deny unless matched)
        CP->>H: append request.{action}.denied
        CP->>CP: reputation -= 3 (violation -5, auto-suspend)
        CP-->>A: {decision: deny, reason, policy}
    end
```

Delegation extends the same model: a delegator signs a capability token scoped
to `{actions, datasets, domains}` with a depth limit and TTL. A delegated agent
inherits authority only inside that exact scope, and every hop in the chain is
itself audited.

## Components

| Component | File | Responsibility |
| --------- | ---- | -------------- |
| Gateway | `app/routers/requests.py` | Verify signature, run `evaluate_signed()`, return decision |
| Policy | `app/policy.py`, `app/opa.py` | Ordered default-deny rules; pushes Rego to OPA at startup, auto fallback |
| Reputation | `app/reputation.py` | Tiers, allow/deny/violation scoring, auto-suspend |
| Delegation | `app/delegation.py` | Scope validation, depth chain, capability tokens |
| Audit | `app/hashchain.py` | SHA-256 chain + Ed25519 signatures, `verify_chain` |
| DataHub | `app/datahub/` | Catalog + GraphQL client with optional MCP-server reads; agent impact contributed via MetadataChangeProposal ingest; `catalog.py` also seeds the bundled reference catalog when no DataHub is configured |
| Criticality | `app/datahub/criticality.py` | Dataset scores from PageRank centrality, agent impact, classification risk, blast radius |
| Monitor | `app/datahub/monitor.py` | Guardian scans, watchlist thresholds, breach events written to the audit chain |
| Impact | `app/datahub/impact_analysis.py` | Blast radius, what-if chaos experiments, predicted agents, risk prediction |
| Agents | `agents/` | LangGraph workflow, planner, tools, worker |
| SDK | `sdk/controlplane.py` | Real agents use this to sign & act |
| Telemetry | `app/telemetry.py` | MELT: metrics, events, logs, traces |
| Runtime | `scripts/docker/entrypoint.sh` | Starts bundled OPA + uvicorn + worker; picks engine by OPA presence |

## DataHub context: catalog, criticality & impact

Everything below derives from the catalog (domains, classifications, owners,
lineage DAGs) plus the control plane's own recorded agent actions — no external
scoring service. The catalog itself has two interchangeable sources:

- **Live DataHub** — when `DATAHUB_ENDPOINT` (+ optional `DATAHUB_TOKEN`) is
  set, rows are synced via GraphQL search/lineage.
- **Bundled reference catalog** — a curated seed (`seed_reference_catalog`,
  `app/datahub/catalog.py`) loaded at every boot when no DataHub is reachable.
  Stale sync rows are pruned (`_prune_stale_syncs`), so a demo never mixes
  generic synced noise with the curated stack.

`GET /api/datahub/status` → `catalog_source: "datahub" | "reference"` drives the
console's **Live DataHub catalog / Reference catalog mode** badge.

```mermaid
flowchart LR
    DH2[DataHub GMS<br/>GraphQL reads +<br/>MetadataChangeProposal writes] --> CAT2[catalog.py]
    MCP2[DataHub MCP server<br/>optional USE_DATAHUB_MCP] -.-> CAT2
    ACT[recorded agent actions] --> IMP2[impact.py]
    CAT2 --> LINE[lineage_sims.py]
    CAT2 --> CRIT2[criticality.py]
    IMP2 --> CRIT2
    LINE --> CRIT2
    CRIT2 --> MON[monitor.py<br/>watchlist + guardian scan]
    CRIT2 --> WIF[impact_analysis.py<br/>blast radius · what-if]
    IMP2 --> WIF
    WIF --> PRED[prediction + predicted agents]
    MON --> HC2[(hash-chain audit)]
    WIF --> HC2
```

- **Criticality** — each dataset is scored as `0.35·centrality + 0.25·impact +
  0.20·risk + 0.20·blast`, where centrality is a lineage PageRank, impact is
  recorded agent activity weight, risk comes from classification, and blast is
  the size of the downstream subgraph. Watchlist entries add per-entity
  thresholds; crossings surface as alerts and, on demand, as audited
  `datahub.watchlist.breach` chain events.
- **Guardian scans** — the `ag_monitor` guardian runs the same governed
  workflow as any agent, producing a persisted `MonitorScan` (risk posture,
  criticality deltas, policy gaps, watchlist alerts, findings) that is audited.
- **What-if analysis** — each kind (outage, classification change, schema
  change, ownership transfer, data quality, new upstream, staleness, schema
  drift) walks the lineage graph with its own propagation semantics:
  consumers inherit the failure, schema-affecting kinds are evidence-based
  (only entities with recorded transform/write actions plus consuming jobs are
  marked affected). Results include a modeled risk/likelihood prediction and,
  when no agent has touched the subgraph, agents predicted to be impacted from
  delegations + domain grants.

## Optional external DataHub integrations

Two official DataHub tools can be enabled by config and are never required — the
control plane keeps working unchanged when they are off or unreachable:

- **DataHub MCP server** (`@acryldata/mcp-server-datahub`, PyPI
  `mcp-server-datahub`) — with `USE_DATAHUB_MCP=true`, catalog search and
  lineage reads go through the server's `search` / `get_lineage` tools instead
  of raw GraphQL. The server is spawned over stdio (`DATAHUB_MCP_COMMAND`,
  default `uvx mcp-server-datahub@latest`) or reached over an SSE endpoint
  (`DATAHUB_MCP_URL`). If the MCP server is unreachable, `app/datahub/client.py`
  transparently falls back to GraphQL, so a broken MCP process never breaks the
  catalog. Writes are unaffected: agent-impact contribution always uses DataHub's
  MetadataChangeProposal ingest API. Read provider is surfaced in
  `/api/datahub/status` → `providers.datahub_read`.
- **DataHub analytics agent** (`datahub-project/analytics-agent`, PyPI
  `datahub-analytics-agent`) — with `USE_ANALYTICS_AGENT=true`,
  `POST /api/datahub/analytics` answers a natural-language question by calling a
  running analytics-agent service (`ANALYTICS_AGENT_URL`, default
  `http://localhost:8100`) and returns the agent's text/SQL/chart. Otherwise the
  endpoint answers from the built-in catalog search. The analytics agent is a
  separate deployable service (FastAPI, LangGraph ReAct, SSE chat), so this
  control plane only ever talks to it over HTTP. Provider is surfaced in
  `/api/datahub/status` → `providers.analytics`.

## Governed LangGraph agents

```mermaid
flowchart LR
    OBJ[NL objective] --> PL[planner node]
    PL -->|"plan [{action, resource}]"| EX[executor node]
    EX -->|governed tool call| GW2[(gateway)]
    GW2 -->|decision| EX
    EX -->|results + denied flag| SUM[summarizer node]
    SUM --> OUT[summary]
    EX --> MET2["OTel span agents.{action}"]
    PL --> MET2
```

* `workflow.py` — `StateGraph(AgentState)` with nodes `planner → executor →
  summarizer`, compiled with a `MemorySaver` checkpointer keyed by `thread_id`.
* `planner.py` — LiteLLM planner when `LLM_MODEL` is set; otherwise a
  role-aware rule-based planner (`query`/`transform`/`write` resolution with
  token-overlap entity matching against the catalog).
* `tools.py` — `GovernedToolSet` wraps the gateway: every `read/query/transform/
  write/ingest/deploy` call is a signed request that is governed, audited, and
  scored, whether the graph runs in-process or over HTTP from the worker.
* `runner.py` — `execute_run(agent_id, objective, mode)`:
  `inprocess` (sync runs/tests) or `http` (worker — keys live only in the
  agent runtime).
* `worker.py` — claims `pending` runs from `/api/runs/pending`, executes them,
  and posts outcomes back to `/api/runs/{id}/complete`.

## Telemetry — MELT, vendor-neutral

All four signal types are emitted through one configurable pipeline:

| Signal | What | Where |
| ------ | ---- | ----- |
| **M**etrics | `gateway.decisions`, `agents.runs`, `http.client.duration` | `metrics.jsonl` / OTLP `/v1/metrics` |
| **E**vents | every audit-chain event (`request.query`, `request.query.denied`, `agent.run.*`, …) mirrored with the `event.name` attribute | `logs.jsonl` / OTLP `/v1/logs` |
| **L**ogs | worker lifecycle, structured log records | `logs.jsonl` / OTLP `/v1/logs` |
| **T**races | `agents.plan`, `agents.execute`, `agents.{action}`, gateway/HTTP spans | `traces.jsonl` / OTLP `/v1/traces` |

Exporters are selectable with `CONTROLPLANE_TELEMETRY_EXPORTER`:
`file` (default, JSON Lines), `otlp` (any OTLP collector), `console`, or `none`.
No cloud-vendor SDK is used. See `backend/.env.example` and [SETUP.md](SETUP.md#telemetry).

## Deployment & runtime

The whole app ships as **one container** — the React console is built in a
first stage and served from the same FastAPI process (no separate frontend
server), the bundled OPA binary runs in-container on `127.0.0.1:8181`, and the
agent worker runs alongside the API. `scripts/docker/entrypoint.sh` starts all
three processes and defaults `SELF_URL` to the loopback so the worker polls the
container directly.

```mermaid
flowchart TB
    subgraph SRC[Source]
        FR[frontend/ · React + Vite + TS]
        BK[backend/ · FastAPI + agents + SDK]
        REGO[policies/datahub.rego]
    end

    subgraph IMG[One Docker image — Dockerfile, multi-arch amd64 + arm64]
        S1[node:20-alpine build stage<br/>npm ci → dist]
        S2[python:3.12-slim runtime<br/>+ tini + bundled OPA binary]
        E[entrypoint.sh]
        WEB[uvicorn app.main :$PORT]
        OPA[opa run :8181]
        WK[agents.worker]
        DATA[(/app/backend/data<br/>SQLite · telemetry JSONL · demo keys)]
    end

    FR --> S1
    S1 --> S2
    BK --> S2
    REGO --> S2
    S2 --> E
    E --> OPA
    E --> WEB
    E --> WK
    OPA -->|pushes datahub.rego| WEB
    WK -->|claims /api/runs/pending| WEB
    DATA --> WEB
    DATA --> WK

    subgraph HOST[Hosts]
        R[Render web service<br/>health check /health<br/>plan free or starter]
        VC[Vercel Fluid compute<br/>worker disabled]
        VM[Any VM / Dokku / ECS]
    end
    IMG --> HOST
    R -->|persistent disk| DATA
```

- **Ports:** container listens on `$PORT` (default `8080`; Render/Vercel inject
  their own). `EXPOSE 8080 8181`.
- **Worker:** `CONTROLPLANE_RUN_WORKER=true` (default in the image) runs the
  async run queue in-process; the Vercel variant ships it disabled
  (`Dockerfile.vercel`) so console runs fall back to `sync`.
- **Persistence:** mount `/app/backend/data` for durable SQLite + telemetry
  (Render `controlplane-data` disk, local volume, or compose volume). Without a
  mount, the DB reseeds the demo data + reference catalog on every boot.
- **Render image requires `linux/amd64`**; `scripts/render/deploy.sh` builds and
  pushes a multi-arch manifest (`linux/amd64,linux/arm64`) to Docker Hub first,
  then drives the Render API (`POST /services`, deploy trigger, status poll).

## Configuration

*Everything* is configured through `backend/app/config.py` (pydantic-settings)
read from the environment or `backend/.env`. There are no hard-coded
deployment values in application code; the defaults shown in the table below
are overridable by the matching env var.

| Setting | Env var | Default |
| ------- | ------- | ------- |
| Bind address | `HOST` / `PORT` | `0.0.0.0` / `5186` |
| Own URL | `SELF_URL` | `http://localhost:5186` |
| SDK base | `CONTROLPLANE_URL` | `http://localhost:5186` |
| Database | `DATABASE_URL` | `sqlite:///./data/controlplane.db` |
| Policy engine | `CONTROLPLANE_POLICY_ENGINE` / `POLICY_ENGINE` | `auto` |
| OPA endpoint | `CONTROLPLANE_OPA_URL` / `OPA_URL` | `http://localhost:8181` |
| OPA policy | `CONTROLPLANE_OPA_POLICY_NAME` / `CONTROLPLANE_OPA_POLICY_FILE` | `controlplane` / `policies/datahub.rego` |
| Run worker | `CONTROLPLANE_RUN_WORKER` | `false` locally; `true` in the container |
| DataHub | `DATAHUB_ENDPOINT` / `DATAHUB_TOKEN` | `` (offline catalog) |
| DataHub MCP reads | `USE_DATAHUB_MCP` / `DATAHUB_MCP_COMMAND` / `DATAHUB_MCP_URL` | `false` / `uvx mcp-server-datahub@latest` / `` |
| Analytics agent | `USE_ANALYTICS_AGENT` / `ANALYTICS_AGENT_URL` / `ANALYTICS_AGENT_ENGINE` | `false` / `http://localhost:8100` / `` |
| LLM planner | `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_TEMPERATURE` | `` (rule-based) |
| Worker poll | `WORKER_POLL_INTERVAL` / `WORKER_NAME` | `5.0` / `worker-default` |
| Telemetry | `CONTROLPLANE_TELEMETRY_*` + standard `OTEL_*` | `file` exporter |

## Demo / simulation scenarios

See [SETUP.md](SETUP.md#demo-scenarios) for runnable walkthroughs and the
console's **Zero-Trust Lab** for a self-driving scenario that exercises the
whole stack live.
