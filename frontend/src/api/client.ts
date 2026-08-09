import type {
  Agent,
  AgentBlastRadius,
  AgentKeyPair,
  AgentRun,
  ActionTrace,
  AuditEvent,
  AuditTrace,
  BlastRadius,
  ChainVerify,
  CriticalityReport,
  DashboardSummary,
  DataHubEntity,
  DataHubExperiment,
  Delegation,
  DelegationCreated,
  GatewayResponse,
  ImpactAgentDetail,
  ImpactEntityDetail,
  ImpactMatrix,
  Policy,
  PolicyGapPreview,
  PolicyGapReport,
  ScenarioDef,
  ScenarioExecution,
  ScenarioPreview,
  ScenarioTransformResult,
  TamperResult,
  WatchlistAlert,
  WatchlistResponse,
  MonitorScan,
  WhatIfResult,
} from './types'

// Base is configuration-only: VITE_API_URL when set (e.g. a separately-hosted
// API), otherwise the same origin — vite dev/preview proxies /api to the
// control plane (see vite.config.ts).
const BASE = import.meta.env.VITE_API_URL || ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error((body as { detail?: string }).detail || `request failed: ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  // agents
  listAgents: () => request<Agent[]>('/api/agents'),
  getAgent: (id: string) => request<Agent>(`/api/agents/${id}`),
  registerAgent: (body: { name: string; description: string; public_key: string; granted_domains: string[] }) =>
    request<AgentKeyPair>('/api/agents/register', { method: 'POST', body: JSON.stringify(body) }),
  generateKeys: () => request<AgentKeyPair>('/api/agents/keypair', { method: 'POST' }),
  setAgentStatus: (id: string, status: string) =>
    request<Agent>(`/api/agents/${id}/status`, { method: 'POST', body: JSON.stringify({ status }) }),
  reputation: (id: string) => request<{ agent_id: string; tier: string; trust_score: number; timeline: unknown[] }>(`/api/agents/${id}/reputation`),

  // agent runs (governed LangGraph agents)
  listRuns: (agentId?: string) =>
    request<AgentRun[]>(`/api/runs${agentId ? `?agent_id=${agentId}` : ''}`),
  runAgent: (agentId: string, objective: string, sync = false) =>
    request<AgentRun>(`/api/agents/${agentId}/run`, {
      method: 'POST',
      body: JSON.stringify({ agent_id: agentId, objective, sync }),
    }),

  // delegations
  listDelegations: () => request<Delegation[]>('/api/delegations'),
  createDelegation: (body: object) => request<DelegationCreated>('/api/delegations', { method: 'POST', body: JSON.stringify(body) }),
  revokeDelegation: (id: string) => request<Delegation>(`/api/delegations/${id}/revoke`, { method: 'POST' }),

  // gateway
  gateway: (body: object) => request<GatewayResponse>('/api/requests/gateway', { method: 'POST', body: JSON.stringify(body) }),

  // audit
  listAudit: (params: { limit?: number; event_type?: string; agent_id?: string; decision?: string } = {}) => {
    const qs = new URLSearchParams()
    if (params.limit) qs.set('limit', String(params.limit))
    if (params.event_type) qs.set('event_type', params.event_type)
    if (params.agent_id) qs.set('agent_id', params.agent_id)
    if (params.decision) qs.set('decision', params.decision)
    const q = qs.toString()
    return request<AuditEvent[]>(`/api/audit${q ? `?${q}` : ''}`)
  },
  verifyChain: () => request<ChainVerify>('/api/audit/verify/chain'),
  repairChain: () => request<ChainVerify>('/api/audit/repair', { method: 'POST' }),
  simulateTamper: (seq?: number) => {
    const qs = seq != null ? `?seq=${seq}` : ''
    return request<TamperResult>(`/api/audit/simulate-tamper${qs}`, { method: 'POST' })
  },
  auditTrace: (eventId: string) =>
    request<AuditTrace>(`/api/audit/${encodeURIComponent(eventId)}/trace`),
  exportAudit: async (format: 'csv' | 'json' = 'csv') => {
    const res = await fetch(`${BASE}/api/audit/export?format=${format}`)
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error((body as { detail?: string }).detail || `export failed: ${res.status}`)
    }
    return res.text()
  },

  // policies
  listPolicies: () => request<Policy[]>('/api/policies'),
  createPolicy: (body: object) => request<Policy>('/api/policies', { method: 'POST', body: JSON.stringify(body) }),
  setPolicyEnabled: (id: string, enabled: boolean) =>
    request<Policy>(`/api/policies/${id}/enabled?enabled=${enabled}`, { method: 'PATCH' }),
  deletePolicy: (id: string) => request<{ deleted: string }>(`/api/policies/${id}`, { method: 'DELETE' }),

  // datahub
  datahubStatus: () => request<{
    endpoint: string
    connected: boolean
    catalog_source: string
    providers: {
      datahub_read: string
      analytics: string
      mcp_url: string
      analytics_agent_url: string
    }
  }>('/api/datahub/status'),
  entities: (params: { domain?: string; classification?: string } = {}) => {
    const qs = new URLSearchParams()
    if (params.domain) qs.set('domain', params.domain)
    if (params.classification) qs.set('classification', params.classification)
    const q = qs.toString()
    return request<DataHubEntity[]>(`/api/datahub/entities${q ? `?${q}` : ''}`)
  },
  impact: () => request<ImpactMatrix>('/api/datahub/impact'),
  recordDatahubAction: (body: object) => request<object>('/api/datahub/actions', { method: 'POST', body: JSON.stringify(body) }),
  actionTrace: (actionId: string) =>
    request<ActionTrace>(`/api/datahub/actions/${encodeURIComponent(actionId)}/trace`),
  blastRadius: (urn: string, depth = 3) =>
    request<BlastRadius>(`/api/datahub/impact/blast/${encodeURIComponent(urn)}?depth=${depth}`),
  agentBlastRadius: (agentId: string) =>
    request<AgentBlastRadius>(`/api/datahub/impact/agent/${encodeURIComponent(agentId)}/blast`),
  runWhatIf: (body: { root_urn: string; kind: string; params?: Record<string, unknown> }) =>
    request<WhatIfResult>('/api/datahub/impact/what-if', { method: 'POST', body: JSON.stringify(body) }),
  runCustomExperiment: (body: { name?: string; blueprint: Array<{ root_urn: string; kind: string; params?: Record<string, unknown> }> }) =>
    request<WhatIfResult>('/api/datahub/experiments/custom', { method: 'POST', body: JSON.stringify(body) }),
  listExperiments: () => request<DataHubExperiment[]>('/api/datahub/experiments'),
  getExperiment: (id: string) =>
    request<DataHubExperiment & { result: WhatIfResult }>(`/api/datahub/experiments/${id}`),
  impactForAgent: (agentId: string) => request<ImpactAgentDetail>(`/api/datahub/impact/agent/${encodeURIComponent(agentId)}`),
  impactForEntity: (urn: string) => request<ImpactEntityDetail>(`/api/datahub/impact/entity/${encodeURIComponent(urn)}`),
  criticality: () => request<CriticalityReport>('/api/datahub/criticality'),
  watchlist: () => request<WatchlistResponse>('/api/datahub/watchlist'),
  watchlistAlerts: () => request<{ count: number; alerts: WatchlistAlert[] }>('/api/datahub/watchlist/alerts'),
  addWatchlist: (body: { urn: string; threshold: number }) =>
    request<{ id: number; urn: string; threshold: number; created_at: string }>('/api/datahub/watchlist', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  removeWatchlist: (id: number) => request<{ removed: number; urn: string }>(`/api/datahub/watchlist/${id}`, { method: 'DELETE' }),
  runMonitorScan: () => request<MonitorScan>('/api/datahub/monitor/scan', { method: 'POST' }),
  monitorScans: () => request<MonitorScan[]>('/api/datahub/monitor/scans'),
  getMonitorScan: (scanId: string) => request<MonitorScan>(`/api/datahub/monitor/scans/${encodeURIComponent(scanId)}`),
  recordWatchlistBreaches: () =>
    request<{ recorded: number; alerts: Array<{ urn: string; name: string; current: number; threshold: number }> }>(
      '/api/datahub/watchlist/breaches',
      { method: 'POST' },
    ),
  policyGaps: () => request<PolicyGapReport>('/api/datahub/policy-gaps'),
  previewPolicyGap: (gapId: string) =>
    request<PolicyGapPreview>(`/api/datahub/policy-gaps/${encodeURIComponent(gapId)}/preview`),
  applyPolicyGap: (gapId: string) =>
    request<Policy>(`/api/datahub/policy-gaps/${encodeURIComponent(gapId)}/apply`, { method: 'POST' }),

  // zero-trust lab scenarios
  listScenarios: () => request<ScenarioDef[]>('/api/demo/scenarios'),
  transformScenario: (body: { scenario_id?: string; objective?: string; agents?: string[] }) =>
    request<ScenarioTransformResult>('/api/demo/scenarios/transform', { method: 'POST', body: JSON.stringify(body) }),
  previewScenario: (planId: string) =>
    request<ScenarioPreview>('/api/demo/scenarios/preview', { method: 'POST', body: JSON.stringify({ plan_id: planId }) }),
  approveScenario: (planId: string) =>
    request<ScenarioExecution>('/api/demo/scenarios/approve', { method: 'POST', body: JSON.stringify({ plan_id: planId }) }),
  rejectScenario: (planId: string) =>
    request<{ plan_id: string; status: string }>('/api/demo/scenarios/reject', { method: 'POST', body: JSON.stringify({ plan_id: planId }) }),
  resetLab: () => request<{ policies_removed: number; agents_restored: boolean }>('/api/demo/scenarios/reset', { method: 'POST' }),

  // dashboard
  summary: () => request<DashboardSummary>('/api/dashboard/summary'),
}
