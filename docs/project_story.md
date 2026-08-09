# Agent Control Plane — Project Story

> **Govern every AI action. Trust nothing by default.**

## Inspiration

AI agents are being handed real power — reading databases, changing data, and
making decisions that affect customers, finance, and sensitive systems. In
most deployments, that power is not governed: nobody can answer who is allowed
to act, why an agent is trusted, what it did, or whether the trail can be
trusted.

That gap inspired Agent Control Plane: a zero-trust gateway that sits between
agents and data, treating agents as first-class principals with identity,
policy, delegation bounds, and an auditable ledger.

## What it does

- Issues Ed25519 identities to agents and requires a signed envelope on every
  action.
- Decides every action with default-deny policy in both native Python and
  OPA/Rego, gated by a live reputation tier.
- Bounds delegation with cryptographically scoped `{actions, datasets, domains}`
  tokens.
- Records every event in a SHA-256 + Ed25519 hash chain that detects tampering.
- Uses DataHub as governance substrate, pulling domains, classification,
  lineage, and ownership into criticality, monitoring, and impact analysis.

## How we built it

The stack is intentionally simple where it should be, and purpose-built where it
needs to be: FastAPI + SQLite for the control plane, React/Vite for the console,
LangGraph for governed agents, and OpenTelemetry for telemetry.

Key design choices:

- Signed request envelopes ensure no implicit trust. The client canonicalizes and
  signs the payload, and the server re-canonicalizes before verification.
- Reputation is a live, audited score. Actions adjust a clamped score in
  `[0,100]`, with tiers from `untrusted` to `privileged` and sanctions for
  repeated violations.
- DataHub lineage is treated as security data, not just metadata. Criticality is
  derived from lineage centrality, impact, classification risk, and blast
  radius.
- The audit ledger stores every event as a hash-chained, agent-signed block,
  making tampering visible and verifiable.
- The product is deployable as one multi-arch image with bundled OPA and a
  Python SDK for real agents.

## Challenges we ran into

- Making governance feel alive required a live scenario, not just backend rules.
  We built a Zero-Trust Lab that shows reputation, delegation, and denials in
  real time.
- Deployment needed to work across Apple Silicon development and Linux/amd64
  hosting. We solved that with `docker buildx` multi-arch builds and runtime
  selection of the correct OPA binary.
- Free hosting environments have no persistent disk and can spin down quickly.
  We made boot-time reseeding first-class so the app starts fully populated even
  after cold boots.
- Documenting the architecture across two engines and one story was hard. We
  narrowed the narrative until a single Mermaid sequence diagram captured the
  signed-request flow clearly.

## Accomplishments that we're proud of

- A governance plane with real cryptographic identity, policy, delegation, and
  audit, not just policy checks around a prompt.
- Dual policy engines so native Python decisions can be cross-checked by OPA,
  improving resilience and drift detection.
- A hash-chained audit ledger that detects tampering and ties every event back to
  the signing agent.
- A DataHub-integrated criticality model that uses real lineage, ownership, and
  classification data.
- A deployable, self-seeding system that works even in low-resource or ephemeral
  hosting environments.

## What we learned

- Policy is a product, not a setting. The hard part is explainability, audit, and
  live mutability, not just allow/deny.
- Default-deny changes the threat model: missing grants become visible denials,
  not silent failures.
- Dual engines are a feature. Two implementations of the same rules surface
  drift and keep the system running when one engine is unavailable.
- Demo dependencies need a lightweight fallback. A reference catalog mode makes
  the app work without a full DataHub stack while clearly signaling limited mode.

## What's next for Agent Control Plane

- Cross-engine policy verification in CI to compare native and OPA decisions.
- Streaming the audit chain into DataHub so the ledger lives alongside governed
  metadata.
- Policy-as-code for agents: let domain owners author policy naturally and
  compile it to both execution engines.
