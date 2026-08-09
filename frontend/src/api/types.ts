export type Tier = 'untrusted' | 'standard' | 'elevated' | 'privileged'
export type AgentStatus = 'active' | 'suspended' | 'revoked'
export type RunStatus = 'pending' | 'running' | 'succeeded' | 'denied' | 'failed'

export interface AgentRunResult {
  action: string
  resource: string
  decision: string
  reason: string
  policy: string
  audit_seq: number | null
  result?: Record<string, unknown> | null
}

export interface AgentRun {
  id: string
  agent_id: string
  objective: string
  status: RunStatus
  plan: Array<{ action: string; resource: string }>
  results: AgentRunResult[]
  summary: string
  trace_id: string
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface Agent {
  id: string
  name: string
  description: string
  status: AgentStatus
  tier: Tier
  trust_score: number
  granted_domains: string[]
  created_at: string
  last_seen: string | null
}

export interface AgentKeyPair {
  id: string
  name: string
  private_key: string
  public_key: string
}

export interface ReputationPoint {
  ts: string
  delta: number
  score: number
  tier: string
  reason: string
}

export interface Delegation {
  id: string
  delegator_id: string
  delegatee_id: string
  scope: { actions?: string[]; datasets?: string[]; domains?: string[] }
  max_depth: number
  depth: number
  active: boolean
  status: 'active' | 'expired' | 'revoked'
  issued_at: string
  expires_at: string | null
  revoked_at: string | null
}

export interface DelegationCreated extends Delegation {
  token: string
}

export interface Policy {
  id: string
  name: string
  description: string
  effect: 'allow' | 'deny'
  actions: string[]
  conditions: Array<Record<string, unknown>>
  order: number
  enabled: boolean
  created_at: string
}

export interface AuditEvent {
  id: string
  seq: number
  prev_hash: string
  event_hash: string
  event_type: string
  actor_id: string
  subject: string
  payload: Record<string, unknown>
  decision: string | null
  signed_by: string | null
  ts: string
}

export interface ChainVerify {
  block_count: number
  head: string | null
  valid: boolean
  issues: Array<{ seq: number; kind: string; detail: string }>
  events?: Array<{ seq: number; id: string; event_type: string; actor_id: string; decision: string | null; hash: string; prev_hash: string; signed_by: string | null }>
}

export interface AuditTraceLink {
  seq: number
  event_id: string
  event_type: string
  decision: string | null
}

export interface TraceAction {
  id: string
  entity_urn: string
  action_type: string
  impact_weight: number
  metadata: Record<string, unknown>
  ts: string
  audit?: AuditTraceLink | null
}

export interface TraceEntity {
  urn: string
  name: string
  type: string
  platform: string
  domain: string
  data_classification: string
  owner_team: string
  description?: string
  source?: string
  lineage_facts?: {
    upstream_restricted: boolean
    upstream_restricted_count: number
    downstream_count: number
    is_critical: boolean
    criticality: number
  }
  upstream?: Array<{ urn: string; name?: string; data_classification?: string }>
  downstream?: Array<{ urn: string; name?: string; data_classification?: string }>
}

export interface TraceExperiment {
  id: string
  name: string
  kind: string
  root_urn: string
  risk: string
  status: string
  created_at: string
}

export interface PolicyDecisionInfo {
  id: string
  request_id: string
  decision: string
  reason: string
  engine: string
  policy_input: Record<string, unknown>
  audit_event_id: string | null
  ts: string
}

export interface AuditTrace {
  event: AuditEvent
  policy_decision: PolicyDecisionInfo | null
  action: TraceAction | null
  entity: TraceEntity | null
  experiments: TraceExperiment[]
}

export interface ActionTrace {
  action: TraceAction
  agent: { agent_id: string; name: string; tier: string; status: string }
  audit: AuditTraceLink | null
  entity: TraceEntity | null
  experiments: TraceExperiment[]
}

export interface TamperRun {
  agent_id: string
  role: string
  objective: string
  thread_id: string
  plan: Array<{ action: string; resource: string }>
  plan_source: string
  results: AgentRunResult[]
  summary: string
  status: string
}

export interface TamperResult {
  seq: number
  tampered: boolean
  hash: string
  agent_run: TamperRun | null
}

export interface GatewayResponse {
  request_id: string
  decision: 'allow' | 'deny'
  reason: string
  engine: string
  policy_name: string
  agent_id: string
  event_id: string
  audit_seq: number
  result?: {
    entity?: {
      urn: string
      name: string
      platform: string
      domain: string
      data_classification: string
      owner_team: string
      description: string
      schema: Array<{ name: string; type: string }>
      usage: Record<string, unknown>
    }
    upstream?: string[]
    downstream?: string[]
    resource?: string
    note?: string
  }
}

export interface DataHubEntity {
  urn: string
  name: string
  type: string
  platform: string
  domain: string
  data_classification: string
  owner_team: string
  description: string
  schema: Array<{ name: string; type: string }>
  upstream: string[]
  downstream: string[]
  usage: { queryCount?: number; uniqueUsers?: number; p99LatencyMs?: number }
  source: string
}

export interface ImpactMatrix {
  matrix: Record<string, Record<string, number>>
  counts: Record<string, Record<string, number>>
  weights: Record<string, number>
}

export interface GraphNode {
  id: string
  position: { x: number; y: number }
  type: string
  data: {
    label: string
    cls: string
    kind: string
    root: boolean
    affected: boolean
    reason?: string
    domain?: string
    depth?: number
  }
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  animated?: boolean
  markerEnd?: { type: 'arrow' | 'arrowclosed' }
  style?: Record<string, string>
}

export interface ImpactAgent {
  agent: { agent_id: string; name: string; tier: string; status: string }
  count: number
  weight: number
  actions: string[]
  entities: string[]
  will_be_denied?: boolean
  denied_actions?: string[]
  impacted?: boolean
  reason?: string
  predicted?: boolean
}

export interface ImpactDataset {
  urn: string
  name: string
  domain: string
  data_classification: string
  owner_team: string
  depth: number
  affected?: boolean
  reason?: string
}

export interface ImpactPrediction {
  risk: 'low' | 'medium' | 'high'
  likelihood: 'low' | 'medium' | 'high'
  summary: string
  signals: { impacted_datasets: number; impacted_agents: number; denied_agents: number }
}

export interface BlastRadius {
  root: {
    urn: string
    name: string
    type: string
    platform: string
    domain: string
    data_classification: string
    owner_team: string
    description: string
  } | null
  downstream: ImpactDataset[]
  agents: ImpactAgent[]
  predicted_agents?: ImpactAgent[]
  prediction?: ImpactPrediction
  summary: {
    root: string
    impacted_datasets: number
    impacted_agents: number
    max_depth: number
    restricted_count: number
    sensitive_count: number
  }
  graph: { nodes: GraphNode[]; edges: GraphEdge[] }
}

export interface AgentBlastRadius {
  agent: { agent_id: string; name: string; tier: string; status: string }
  datasets: Array<{
    urn: string
    entity: DataHubEntity | null
    count: number
    weight: number
    actions: string[]
    downstream: ImpactDataset[]
  }>
  total_actions: number
  graph: { nodes: GraphNode[]; edges: GraphEdge[] }
}

export type WhatIfKind =
  | 'outage'
  | 'classification_change'
  | 'schema_change'
  | 'ownership_change'
  | 'data_quality'
  | 'new_upstream'
  | 'staleness'
  | 'schema_drift'
  | 'custom'

export interface CustomExperimentStep {
  root_urn: string
  root_name: string
  kind: WhatIfKind
  params: Record<string, unknown>
  risk: 'low' | 'medium' | 'high'
  impacted_datasets: number
  impacted_agents: number
  denied_agents: number
  max_depth: number
  recommendations: Array<{ severity: string; title: string; detail: string; action: string }>
}

export interface WhatIfResult {
  experiment_id: string
  kind: WhatIfKind
  root_urn: string
  name?: string
  steps?: CustomExperimentStep[]
  params: Record<string, unknown>
  summary: {
    kind: string
    root_urn: string
    root_name: string
    impacted_datasets: number
    impacted_agents: number
    denied_agents: number
    max_depth: number
    risk: 'low' | 'medium' | 'high'
    steps?: number
  }
  downstream: ImpactDataset[]
  agents: ImpactAgent[]
  predicted_agents?: ImpactAgent[]
  prediction?: ImpactPrediction
  recommendations: Array<{ severity: 'low' | 'medium' | 'high'; title: string; detail: string; action: string }>
  graph: { nodes: GraphNode[]; edges: GraphEdge[] }
}

export interface DataHubExperiment {
  id: string
  kind: WhatIfKind
  name?: string
  root_urn: string
  root_name: string
  params: Record<string, unknown>
  summary: Record<string, unknown>
  risk: string
  status: string
  created_at: string
}

export interface ImpactAgentDetail {
  agent: { agent_id: string; name: string; tier: string; status: string }
  total: number
  actions: Array<{ id: string; entity_urn: string; action_type: string; impact_weight: number; ts: string }>
}

export interface ImpactEntityDetail {
  entity: DataHubEntity | null
  total: number
  actions: Array<{ id: string; agent_id: string; action_type: string; impact_weight: number; ts: string }>
}

export interface CriticalityRow {
  urn: string
  name: string
  type: string
  platform: string
  domain: string
  data_classification: string
  owner_team: string
  source: string
  criticality: number
  centrality: number
  impact: number
  risk: number
  blast: number
  downstream_count: number
  agents: number
  actions: number
  components?: { centrality: number; impact: number; risk: number; blast: number }
}

export interface CriticalityReport {
  count: number
  entities: CriticalityRow[]
  summary: {
    top: Array<{ urn: string; name: string; criticality: number }>
    critical_entities: number
    by_classification: Record<string, number>
    weights: Record<string, number>
  }
}

export interface WatchlistEntry {
  id: number
  urn: string
  name: string
  domain: string
  classification: string
  threshold: number
  current: number
  breached: boolean
  created_at: string
}

export interface WatchlistResponse {
  entries: WatchlistEntry[]
  report: CriticalityReport
}

export interface WatchlistAlert {
  watchlist_id: number
  urn: string
  name: string
  domain: string
  threshold: number
  current: number
  delta: number
  classification: string
}

export interface MonitorFinding {
  kind: 'criticality' | 'policy_gaps' | 'watchlist' | string
  status: string
  detail: string
  severity: 'low' | 'medium' | 'high'
  items?: Array<Record<string, unknown>>
}

export interface MonitorScan {
  id: string
  risk: 'low' | 'medium' | 'high'
  status: string
  summary: {
    agent: string
    run_id: string
    status: string
    planner: string
    risk: string
    critical_datasets: number
    policy_gaps: number
    watchlist_alerts: number
    findings: number
    governed_run: { plan: Array<{ action: string; resource: string }>; summary: string }
  }
  findings: MonitorFinding[]
  created_at: string
}

export interface PolicyGapPatch {
  name: string
  effect: string
  actions: string[]
  conditions: Array<Record<string, unknown>>
  order: number
  summary: string
}

export interface PolicyGap {
  id: string
  type: string
  severity: 'low' | 'medium' | 'high'
  title: string
  detail: string
  agent: { id: string; name: string; tier: string; status: string }
  action_type: string
  denied: Array<{ urn: string; name: string; domain: string; classification: string; reason: string; policy_name: string }>
  patch: PolicyGapPatch | null
}

export interface PolicyGapReport {
  scanned_pairs: number
  count: number
  gaps: PolicyGap[]
}

export interface PolicyGapPreview {
  gap_id: string
  patch: PolicyGapPatch | null
  before: Array<{ entity: string; decision: string; policy: string }>
  after: Array<{ entity: string; decision: string; policy: string }>
  consistent: boolean
  note: string
}

export interface DashboardSummary {
  agents: {
    total: number
    active: number
    suspended: number
    revoked: number
    tiers: Record<Tier, number>
    by_domain?: Record<string, number>
  }
  delegations: { total: number; active: number }
  decisions: {
    total: number
    allow: number
    deny: number
    deny_rate: number
    top_deny_reasons: Array<[string, number]>
  }
  catalog: { entities: number; by_domain: Record<string, number> }
  chain: { block_count: number; valid: boolean }
  recent_events: Array<{ seq: number; event_type: string; actor_id: string; decision: string | null; ts: string }>
}

export interface ScenarioStep {
  agent: string
  action: string
  resource: string
  expect?: string
  note?: string
  delegation?: boolean
  domain?: string
  classification?: string
}

export interface ScenarioDef {
  id: string
  name: string
  description: string
  objective: string
  agents: string[]
  steps: ScenarioStep[]
}

export interface ScenarioPolicy {
  name: string
  description: string
  effect: 'allow' | 'deny'
  actions: string[]
  conditions: Array<Record<string, unknown>>
  order: number
}

export interface ScenarioDelegation {
  delegator_id: string
  delegatee_id: string
  scope: { actions?: string[]; datasets?: string[]; domains?: string[] }
  max_depth: number
}

export interface ScenarioBlueprint {
  agents: string[]
  steps: ScenarioStep[]
  policies: ScenarioPolicy[]
  delegation: ScenarioDelegation | null
}

export interface ScenarioTransformResult {
  plan_id: string
  name: string
  status: string
  scenario_id: string
  blueprint: ScenarioBlueprint
}

export interface ScenarioPrediction {
  index: number
  agent: string
  action: string
  resource: string
  resource_name: string
  domain: string
  classification: string
  delegation: boolean
  note: string
  expected?: string
  predicted: string
  reason: string
  policy: string
  policy_generated: boolean
}

export interface ScenarioPreview {
  plan_id: string
  status: string
  predictions: ScenarioPrediction[]
  proposed_policies: ScenarioPolicy[]
  delegation: ScenarioDelegation | null
}

export interface ScenarioExecutionStep {
  index: number
  agent: string
  action: string
  resource: string
  decision: string
  reason: string
  policy: string
  audit_seq: number | null
  expected?: string
  delegation: boolean
  note?: string
}

export interface ScenarioExecution {
  plan_id: string
  scenario_id: string
  name: string
  policies_created: string[]
  delegation: { id: string; token: string } | null
  steps: ScenarioExecutionStep[]
}
