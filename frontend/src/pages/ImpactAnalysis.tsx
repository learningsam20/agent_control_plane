import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Background,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
  type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api } from '../api/client'
import type {
  AgentBlastRadius,
  BlastRadius,
  DataHubEntity,
  DataHubExperiment,
  GraphEdge,
  GraphNode,
  WhatIfKind,
  WhatIfResult,
} from '../api/types'
import { ClassificationBadge, DataTable, Empty, IconButton, PageHeader, SectionTitle, cap } from '../components/ui'

const KINDS: Array<{ id: WhatIfKind; label: string; hint: string }> = [
  { id: 'outage', label: 'Outage', hint: 'The dataset goes down — which consumers and agents are affected?' },
  { id: 'classification_change', label: 'Classification change', hint: 'Raise the classification — who gets denied?' },
  { id: 'schema_change', label: 'Breaking schema change', hint: 'The schema contract breaks — what breaks downstream?' },
  { id: 'ownership_change', label: 'Ownership change', hint: 'Ownership transfers — what needs to move with it?' },
  { id: 'data_quality', label: 'Data-quality issue', hint: 'Dirty data propagates down the lineage — who inherits it?' },
  { id: 'new_upstream', label: 'New upstream source', hint: 'An unvetted feed joins the lineage — what now depends on it?' },
  { id: 'staleness', label: 'Staleness / ETL failure', hint: 'The upstream job failed — who consumes stale data?' },
  { id: 'schema_drift', label: 'Schema drift', hint: 'Columns drifted from the contract — which consumers break?' },
]

function RiskBadge({ risk }: { risk: string }) {
  return <span className={`badge risk-${risk}`}>{cap(risk)}</span>
}

function SevBadge({ severity }: { severity: string }) {
  return <span className={`badge sev-${severity}`}>{cap(severity)}</span>
}

function ImpactNode({ data }: { data: GraphNode['data'] }) {
  const { label, cls, kind, root, affected, reason, domain, depth } = data
  const radius = typeof depth === 'number' ? depth : 0
  return (
    <div style={{
      border: `2px solid ${root ? 'var(--accent)' : affected ? 'var(--red)' : 'var(--bg-3)'}`,
      boxShadow: affected && radius > 0 ? `0 0 0 ${Math.max(0.5, 2 - radius * 0.4)}px rgba(248,81,73,.18)` : 'none',
      background: root ? 'rgba(79,140,255,.10)' : affected ? 'rgba(248,81,73,.08)' : 'var(--bg-2)',
      borderRadius: 8,
      padding: '8px 12px',
      width: 215,
    }}>
      <div className="mono" style={{ fontWeight: root ? 700 : 600, color: 'var(--text)', wordBreak: 'break-word', overflowWrap: 'anywhere' }}>{label}</div>
      <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <ClassificationBadge cls={cls} />
        {kind && kind !== 'dataset' ? <span className="chip">{kind}</span> : null}
        {root ? <span className="chip" style={{ color: 'var(--accent)', borderColor: 'var(--accent)' }}>Root</span> : null}
        {affected ? <span className="chip" style={{ color: 'var(--red)', borderColor: 'var(--red)' }}>Affected</span> : null}
        {radius > 0 ? <span className="chip" style={{ fontSize: 10 }}>depth {radius}</span> : null}
      </div>
      {domain ? <div style={{ marginTop: 4, fontSize: 11, color: 'var(--muted)' }}>{domain}</div> : null}
      {affected && reason ? <div style={{ marginTop: 4, fontSize: 11, color: 'var(--red)' }}>⚠ {reason}</div> : null}
    </div>
  )
}

const nodeTypes: NodeTypes = { impact: ImpactNode }

function radialLayout(nodes: Node[]): Node[] {
  const rings = new Map<number, Node[]>()
  for (const n of nodes) {
    const d = typeof n.data?.depth === 'number' ? n.data.depth : 0
    const list = rings.get(d) ?? []
    list.push(n)
    rings.set(d, list)
  }
  const out: Node[] = []
  for (const [d, list] of [...rings.entries()].sort((a, b) => a[0] - b[0])) {
    const radius = d * 150
    const start = -Math.PI / 2
    list.forEach((n, i) => {
      const angle = list.length === 1 ? start : start + (2 * Math.PI * i) / list.length
      out.push({ ...n, position: { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius } })
    })
  }
  return out
}

function ImpactGraph({ graph, height = 430, radial = true }: { graph: { nodes: GraphNode[]; edges: GraphEdge[] }; height?: number; radial?: boolean }) {
  const navigate = useNavigate()
  const nodes: Node[] = useMemo(() => {
    const base = graph.nodes.map((n) => ({ ...n, type: 'impact' } as Node))
    return radial ? radialLayout(base) : base
  }, [graph.nodes, radial])
  const edges: Edge[] = useMemo(() => graph.edges.map((e) => ({ ...e })), [graph.edges])
  return (
    <div>
      <div style={{ display: 'flex', gap: 14, marginBottom: 6, fontSize: 11, color: 'var(--muted)', alignItems: 'center' }}>
        <span><i style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 50, background: 'var(--accent)', marginRight: 4 }} /> Root</span>
        <span><i style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 50, background: 'var(--red)', marginRight: 4 }} /> Affected</span>
        <span><i style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 50, border: '1px solid var(--bg-3)', marginRight: 4 }} /> Unaffected</span>
        <span style={{ marginLeft: 'auto' }}>click a node to open its lineage</span>
      </div>
      <div style={{ height, border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ maxZoom: 1 }}
          minZoom={0.3}
          nodesDraggable
          onNodeClick={(_, node) => navigate(`/lineage?urn=${encodeURIComponent(node.id)}`)}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="var(--border)" gap={24} />
          <Controls />
        </ReactFlow>
      </div>
    </div>
  )
}

function SummaryChips({ summary }: { summary: Record<string, unknown> }) {
  const keys = ['impacted_datasets', 'impacted_agents', 'denied_agents', 'max_depth']
  const items = keys.filter((k) => k in summary).map((k) => [k, summary[k]] as const)
  return (
    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
      {items.map(([k, v]) => (
        <div key={k} className="stat" style={{ flex: '0 1 auto', padding: '10px 14px' }}>
          <div className="label">{k.replace(/_/g, ' ')}</div>
          <div className="value" style={{ fontSize: 20 }}>{String(v)}</div>
        </div>
      ))}
    </div>
  )
}

export default function ImpactAnalysis() {
  const navigate = useNavigate()
  const [entities, setEntities] = useState<DataHubEntity[]>([])
  const [experiments, setExperiments] = useState<DataHubExperiment[]>([])
  const [error, setError] = useState('')

  const [blastUrn, setBlastUrn] = useState('')
  const [blastDepth, setBlastDepth] = useState(3)
  const [blast, setBlast] = useState<BlastRadius | null>(null)
  const [blastLoading, setBlastLoading] = useState(false)
  const [blastError, setBlastError] = useState('')

  const [agentId, setAgentId] = useState('ag_analyst')
  const [agentBlast, setAgentBlast] = useState<AgentBlastRadius | null>(null)
  const [agentLoading, setAgentLoading] = useState(false)
  const [agentError, setAgentError] = useState('')

  const [wiUrn, setWiUrn] = useState('')
  const [wiKind, setWiKind] = useState<WhatIfKind>('classification_change')
  const [wiNewCls, setWiNewCls] = useState('restricted')
  const [wiOwner, setWiOwner] = useState('customer-data-team')
  const [wiIssue, setWiIssue] = useState('dirty PII')
  const [wiRows, setWiRows] = useState(0)
  const [wiSource, setWiSource] = useState('urn:li:dataset:(urn:li:dataPlatform:kafka,events.sdk,PROD)')
  const [wiCategory, setWiCategory] = useState('third-party')
  const [wiHours, setWiHours] = useState(24)
  const [wiJob, setWiJob] = useState('etl_marketing_daily')
  const [wiCols, setWiCols] = useState('campaign_id, roi')
  const [wiContract, setWiContract] = useState('v2')
  const [wi, setWi] = useState<WhatIfResult | null>(null)
  const [wiLoading, setWiLoading] = useState(false)
  const [wiError, setWiError] = useState('')

  interface BuilderStep {
    root_urn: string
    kind: WhatIfKind
    params: Record<string, unknown>
  }
  const [builderName, setBuilderName] = useState('')
  const [builderSteps, setBuilderSteps] = useState<BuilderStep[]>([
    { root_urn: '', kind: 'classification_change', params: { new_classification: 'restricted' } },
  ])
  const [builderLoading, setBuilderLoading] = useState(false)
  const [builderError, setBuilderError] = useState('')
  const [drafts, setDrafts] = useState<Array<{ name: string; steps: BuilderStep[] }>>([])
  const [draftNotice, setDraftNotice] = useState('')
  const [openDraft, setOpenDraft] = useState('')

  const DRAFTS_KEY = 'datahub.custom.drafts'
  const loadDrafts = () => {
    try {
      const raw = localStorage.getItem(DRAFTS_KEY)
      if (raw) setDrafts(JSON.parse(raw))
    } catch { /* ignore corrupted drafts */ }
  }

  const resultRef = useRef<HTMLDivElement>(null)
  const scrollToResult = useCallback(() => {
    requestAnimationFrame(() => {
      resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }, [])

  const PRESETS: Array<{ name: string; blueprint: BuilderStep[] }> = [
    {
      name: 'Quarter-end financial review',
      blueprint: [
        { root_urn: 'urn:li:dataset:(urn:li:dataPlatform:bigquery,finance.revenue,PROD)', kind: 'classification_change', params: { new_classification: 'restricted' } },
        { root_urn: 'urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.customer_360,PROD)', kind: 'outage', params: {} },
      ],
    },
    {
      name: 'Marketing pipeline health',
      blueprint: [
        { root_urn: 'urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_events,PROD)', kind: 'staleness', params: { hours_stale: 72, failed_job: 'etl_marketing_daily' } },
        { root_urn: 'urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_attribution,PROD)', kind: 'data_quality', params: { issue: 'duplicate attribution rows' } },
        { root_urn: 'urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_attribution,PROD)', kind: 'schema_drift', params: { broken_columns: ['spend'], contract_version: 'v3' } },
      ],
    },
    {
      name: 'ML governance sweep',
      blueprint: [
        { root_urn: 'urn:li:dataset:(urn:li:dataPlatform:bigquery,ml.churn_features,PROD)', kind: 'classification_change', params: { new_classification: 'restricted' } },
        { root_urn: 'urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model,PROD)', kind: 'new_upstream', params: { source_urn: 'urn:li:dataset:(urn:li:dataPlatform:kafka,events.sdk,PROD)', category: 'unvetted' } },
      ],
    },
  ]

  const setStep = (i: number, patch: Partial<BuilderStep>) => {
    setBuilderSteps((steps) => steps.map((s, idx) => (idx === i ? { ...s, ...patch } : s)))
  }

  const setStepParam = (i: number, key: string, value: unknown) => {
    setBuilderSteps((steps) => steps.map((s, idx) =>
      idx === i ? { ...s, params: { ...s.params, [key]: value } } : s))
  }

  const runBuilder = async () => {
    if (!builderSteps.some((s) => s.root_urn)) return
    setBuilderLoading(true)
    setBuilderError('')
    setDraftNotice('')
    try {
      const r = await api.runCustomExperiment({
        name: builderName,
        blueprint: builderSteps.map((s) => ({ root_urn: s.root_urn, kind: s.kind, params: s.params })),
      })
      setWi(r)
      const exps = await api.listExperiments()
      setExperiments(exps)
      scrollToResult()
    } catch (e) {
      setBuilderError(String((e as Error).message || e))
    } finally {
      setBuilderLoading(false)
    }
  }

  const saveDraft = () => {
    if (!builderName.trim()) {
      setBuilderError('Give the experiment a name before saving.')
      return
    }
    const next = [
      ...drafts.filter((d) => d.name !== builderName.trim()),
      { name: builderName.trim(), steps: JSON.parse(JSON.stringify(builderSteps)) as BuilderStep[] },
    ]
    setDrafts(next)
    try { localStorage.setItem(DRAFTS_KEY, JSON.stringify(next)) } catch { /* ignore */ }
    setBuilderError('')
    setDraftNotice(`Saved "${builderName.trim()}" — load it from the Saved drafts picker.`)
  }

  const loadDraft = (name: string) => {
    const d = drafts.find((x) => x.name === name)
    if (!d) return
    setBuilderName(d.name)
    setBuilderSteps(JSON.parse(JSON.stringify(d.steps)) as BuilderStep[])
    setBuilderError('')
    setDraftNotice(`Loaded "${d.name}".`)
  }

  const deleteDraft = (name: string) => {
    const next = drafts.filter((d) => d.name !== name)
    setDrafts(next)
    try { localStorage.setItem(DRAFTS_KEY, JSON.stringify(next)) } catch { /* ignore */ }
    if (openDraft === name) setOpenDraft('')
    setDraftNotice(`Deleted "${name}".`)
  }

  const entityName = useCallback((urn: string) => entities.find((e) => e.urn === urn)?.name || urn, [entities])

  useEffect(() => {
    loadDrafts()
    api.entities()
      .then((ents) => {
        setEntities(ents)
        const billing = ents.find((e) => e.name.includes('mart_billing'))
        const opps = ents.find((e) => e.name === 'sales.opportunities')
        setWiUrn((prev) => prev || billing?.urn || ents[0]?.urn || '')
        setBlastUrn((prev) => prev || opps?.urn || ents[0]?.urn || '')
      })
      .catch((e) => setError(String((e as Error).message || e)))
    api.listExperiments()
      .then(setExperiments)
      .catch(() => {})
  }, [])

  const runBlast = async () => {
    if (!blastUrn) return
    setBlastLoading(true)
    setBlastError('')
    try {
      const r = await api.blastRadius(blastUrn, blastDepth)
      setBlast(r)
    } catch (e) {
      setBlastError(String((e as Error).message || e))
    } finally {
      setBlastLoading(false)
    }
  }

  const runAgentBlast = async () => {
    setAgentLoading(true)
    setAgentError('')
    try {
      const r = await api.agentBlastRadius(agentId)
      setAgentBlast(r)
    } catch (e) {
      setAgentError(String((e as Error).message || e))
    } finally {
      setAgentLoading(false)
    }
  }

  const runWhatIf = async () => {
    if (!wiUrn) return
    setWiLoading(true)
    setWiError('')
    const params: Record<string, unknown> = {}
    if (wiKind === 'classification_change') params.new_classification = wiNewCls
    if (wiKind === 'ownership_change') params.new_owner = wiOwner
    if (wiKind === 'data_quality') {
      params.issue = wiIssue
      params.rows_affected = wiRows
    }
    if (wiKind === 'new_upstream') {
      params.source_urn = wiSource
      params.category = wiCategory
    }
    if (wiKind === 'staleness') {
      params.hours_stale = wiHours
      params.failed_job = wiJob
    }
    if (wiKind === 'schema_drift') {
      params.broken_columns = wiCols.split(',').map((c) => c.trim()).filter(Boolean)
      params.contract_version = wiContract
    }
    try {
      const r = await api.runWhatIf({ root_urn: wiUrn, kind: wiKind, params })
      setWi(r)
      const exps = await api.listExperiments()
      setExperiments(exps)
      scrollToResult()
    } catch (e) {
      setWiError(String((e as Error).message || e))
    } finally {
      setWiLoading(false)
    }
  }

  const viewExperiment = async (id: string) => {
    setWiLoading(true)
    setWiError('')
    try {
      const r = await api.getExperiment(id)
      const { root_urn, kind } = r.result
      setWiUrn(root_urn)
      setWiKind(kind)
      setWi({ ...r.result, experiment_id: r.id })
      scrollToResult()
    } catch (e) {
      setWiError(String((e as Error).message || e))
    } finally {
      setWiLoading(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Impact Analysis"
        subtitle="DataHub-augmented blast radius and what-if chaos experiments: simulate outages, classification changes, schema changes, ownership transfers, or lineage-reactive conditions (dirty data, a new upstream, staleness, schema drift) and see who is affected."
      />

      {error && <div className="alert deny">{error}</div>}

      <div className="card">
        <SectionTitle hint="Run a simulation against the lineage graph. The result is persisted as an experiment and audited into the hash chain.">
          ⚡ What-if chaos experiment
        </SectionTitle>
        <div className="flow-row">
          <label className="field">
            <span>Dataset</span>
            <select value={wiUrn} onChange={(e) => setWiUrn(e.target.value)}>
              {entities.map((e) => <option key={e.urn} value={e.urn}>{e.name}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Experiment</span>
            <select value={wiKind} onChange={(e) => setWiKind(e.target.value as WhatIfKind)}>
              {KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
            </select>
          </label>
          {wiKind === 'classification_change' && (
            <label className="field">
              <span>New classification</span>
              <select value={wiNewCls} onChange={(e) => setWiNewCls(e.target.value)}>
                <option value="sensitive">sensitive</option>
                <option value="restricted">restricted</option>
              </select>
            </label>
          )}
          {wiKind === 'ownership_change' && (
            <label className="field">
              <span>New owner team</span>
              <input value={wiOwner} onChange={(e) => setWiOwner(e.target.value)} />
            </label>
          )}
          {wiKind === 'data_quality' && (
            <>
              <label className="field">
                <span>Issue</span>
                <input value={wiIssue} onChange={(e) => setWiIssue(e.target.value)} placeholder="e.g. dirty PII" />
              </label>
              <label className="field">
                <span>Rows affected</span>
                <input type="number" min={0} value={wiRows} onChange={(e) => setWiRows(Number(e.target.value))} />
              </label>
            </>
          )}
          {wiKind === 'new_upstream' && (
            <>
              <label className="field" style={{ flex: '1 1 240px' }}>
                <span>New source URN</span>
                <input value={wiSource} onChange={(e) => setWiSource(e.target.value)}
                  placeholder="urn:li:dataset:(urn:li:dataPlatform:kafka,events.sdk,PROD)" />
              </label>
              <label className="field">
                <span>Category</span>
                <select value={wiCategory} onChange={(e) => setWiCategory(e.target.value)}>
                  <option value="third-party">third-party</option>
                  <option value="unvetted">unvetted</option>
                  <option value="vetted">vetted</option>
                </select>
              </label>
            </>
          )}
          {wiKind === 'staleness' && (
            <>
              <label className="field">
                <span>Hours stale</span>
                <input type="number" min={1} value={wiHours} onChange={(e) => setWiHours(Number(e.target.value))} />
              </label>
              <label className="field">
                <span>Failed job</span>
                <input value={wiJob} onChange={(e) => setWiJob(e.target.value)} placeholder="etl_daily" />
              </label>
            </>
          )}
          {wiKind === 'schema_drift' && (
            <>
              <label className="field">
                <span>Broken columns</span>
                <input value={wiCols} onChange={(e) => setWiCols(e.target.value)} placeholder="campaign_id, roi" />
              </label>
              <label className="field">
                <span>Contract version</span>
                <input value={wiContract} onChange={(e) => setWiContract(e.target.value)} placeholder="v2" />
              </label>
            </>
          )}
          <IconButton icon="zap" title="Run experiment" className="primary" onClick={runWhatIf} disabled={wiLoading || !wiUrn} />
        </div>
        <p style={{ color: 'var(--muted)', fontSize: 12, marginTop: 10 }}>
          {KINDS.find((k) => k.id === wiKind)?.hint}
        </p>
        {wiError && <div className="alert deny">{wiError}</div>}

        {wi && (
          <div ref={resultRef} style={{ marginTop: 16 }}>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 10 }}>
              <RiskBadge risk={wi.summary.risk} />
              <span className="mono" style={{ color: 'var(--muted)', fontSize: 12 }}>
                experiment {wi.experiment_id} · {wi.kind} · {entityName(wi.root_urn)}
              </span>
            </div>
            <SummaryChips summary={wi.summary} />
            {wi.prediction && (
              <div className="card" style={{ marginTop: 14 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                  <h3 style={{ margin: 0 }}>Modeled prediction</h3>
                  <RiskBadge risk={wi.prediction.risk} />
                  <span className="chip">likelihood {wi.prediction.likelihood}</span>
                </div>
                <p style={{ margin: '10px 0 0', color: 'var(--text)', fontSize: 13 }}>{wi.prediction.summary}</p>
                <p style={{ margin: '8px 0 0', color: 'var(--muted)', fontSize: 12 }}>
                  {wi.prediction.signals.impacted_datasets} datasets · {wi.prediction.signals.impacted_agents} agents ·{' '}
                  {wi.prediction.signals.denied_agents} denied
                </p>
              </div>
            )}
            {wi.kind === 'custom' && wi.steps && (
              <table className="table" style={{ marginTop: 14 }}>
                <thead>
                  <tr><th>step</th><th>kind</th><th>risk</th><th>datasets</th><th>agents</th><th>denied</th><th>depth</th></tr>
                </thead>
                <tbody>
                  {wi.steps.map((s, i) => (
                    <tr key={i}>
                      <td style={{ fontWeight: 600 }}>{s.root_name}</td>
                      <td className="mono">{s.kind}</td>
                      <td><RiskBadge risk={s.risk} /></td>
                      <td className="mono">{s.impacted_datasets}</td>
                      <td className="mono">{s.impacted_agents}</td>
                      <td className="mono">{s.denied_agents}</td>
                      <td className="mono">{s.max_depth}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div style={{ marginTop: 14 }}><ImpactGraph graph={wi.graph} /></div>

            <div className="grid cols-2" style={{ marginTop: 16 }}>
              <div className="card" style={{ marginBottom: 0 }}>
                <h3>Affected agents</h3>
                <table>
                  <thead>
                    <tr><th>agent</th><th>tier</th><th>actions</th><th>status</th></tr>
                  </thead>
                  <tbody>
                    {wi.agents.length ? wi.agents.map((a) => (
                      <tr key={a.agent.agent_id}>
                        <td className="mono">
                          {a.agent.name}
                          {a.predicted && <span className="chip" style={{ marginLeft: 6 }}>Predicted</span>}
                        </td>
                        <td><span className={`badge tier-${a.agent.tier}`}>{cap(a.agent.tier)}</span></td>
                        <td className="mono">{a.actions.join(', ')}</td>
                        <td>
                          {a.will_be_denied
                            ? <span className="badge decision-deny">Denied: {a.denied_actions?.join(', ')}</span>
                            : a.impacted
                              ? <span className="badge status-active">Impacted</span>
                              : <span className="badge">Unaffected</span>}
                        </td>
                      </tr>
                    )) : <tr><td colSpan={4} style={{ color: 'var(--muted)' }}>No recorded actions in this subgraph.</td></tr>}
                  </tbody>
                </table>
                {wi.predicted_agents && wi.predicted_agents.length > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>
                      Inferred from delegations + domain grants (no recorded action in the subgraph yet):
                    </div>
                    <table>
                      <thead>
                        <tr><th>agent</th><th>tier</th><th>actions</th><th>status</th></tr>
                      </thead>
                      <tbody>
                        {wi.predicted_agents.map((a) => (
                          <tr key={a.agent.agent_id}>
                            <td className="mono">{a.agent.name} <span className="chip">Predicted</span></td>
                            <td><span className={`badge tier-${a.agent.tier}`}>{cap(a.agent.tier)}</span></td>
                            <td className="mono">{a.actions.join(', ')}</td>
                            <td>
                              {a.will_be_denied
                                ? <span className="badge decision-deny">Denied: {a.denied_actions?.join(', ')}</span>
                                : <span className="badge status-active">Impacted</span>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
              <div className="card" style={{ marginBottom: 0 }}>
                <h3>Affected datasets</h3>
                <table>
                  <thead>
                    <tr><th>name</th><th>depth</th><th>reason</th></tr>
                  </thead>
                  <tbody>
                    {wi.downstream.filter((d) => d.affected).length ? wi.downstream.map((d) => (
                      <tr
                        key={d.urn}
                        className="row-click"
                        onClick={() => navigate(`/lineage?urn=${encodeURIComponent(d.urn)}`)}
                        title="Open lineage for this dataset"
                      >
                        <td className="mono">{d.name}</td>
                        <td>{d.depth}</td>
                        <td style={{ color: 'var(--red)' }}>{d.reason}</td>
                      </tr>
                    )) : <tr><td colSpan={3} style={{ color: 'var(--muted)' }}>No downstream datasets affected.</td></tr>}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="card" style={{ marginTop: 16 }}>
              <h3>Recommendations</h3>
              {wi.recommendations.map((r, i) => (
                <div key={i} className="recommendation">
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <SevBadge severity={r.severity} />
                    <strong>{r.title}</strong>
                  </div>
                  <div style={{ color: 'var(--muted)', marginTop: 4, fontSize: 13 }}>{r.detail}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <SectionTitle hint="Compose several what-if steps into one auditable experiment. Each step runs the real engine; the result is aggregated and persisted.">
          🧪 Custom experiment builder
        </SectionTitle>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
          {PRESETS.map((p) => (
            <button
              key={p.name} className="secondary"
              onClick={() => { setBuilderName(p.name); setBuilderSteps(JSON.parse(JSON.stringify(p.blueprint))); setDraftNotice('') }}
            >
              {p.name}
            </button>
          ))}
          <select className="dt-select" value={openDraft} onChange={(e) => loadDraft(e.target.value)} title="Load a saved draft">
            <option value="">Saved drafts…</option>
            {drafts.map((d) => <option key={d.name} value={d.name}>{d.name}</option>)}
          </select>
          {openDraft && <IconButton icon="trash" title="Delete saved draft" className="danger" size={14} onClick={() => deleteDraft(openDraft)} />}
          <IconButton icon="plus" title="Add step" onClick={() => setBuilderSteps((s) => [...s, { root_urn: '', kind: 'outage', params: {} }])} disabled={builderSteps.length >= 8} />
          <IconButton icon="save" title="Save draft" onClick={saveDraft} disabled={!builderName.trim()} />
          <IconButton icon="zap" title="Run custom experiment" className="primary" onClick={runBuilder} disabled={builderLoading || !builderSteps.some((s) => s.root_urn)} />
        </div>
        <label className="field" style={{ marginBottom: 12 }}>
          <span>Experiment name</span>
          <input value={builderName} onChange={(e) => setBuilderName(e.target.value)} placeholder="quarter-end review" />
        </label>
        <div className="builder-grid" style={{ marginBottom: 6 }}>
          <span className="builder-col">Step</span>
          <span className="builder-col">Dataset</span>
          <span className="builder-col">Experiment kind</span>
          <span className="builder-col">Parameters</span>
          <span />
        </div>
        {builderSteps.map((step, i) => (
          <div key={i} className="builder-grid" style={{ marginBottom: 8 }}>
            <span className="builder-step">Step {i + 1}</span>
            <select value={step.root_urn} onChange={(e) => setStep(i, { root_urn: e.target.value })}>
              <option value="">— dataset —</option>
              {entities.map((e) => <option key={e.urn} value={e.urn}>{e.name}</option>)}
            </select>
            <select value={step.kind} onChange={(e) => setStep(i, { kind: e.target.value as WhatIfKind })}>
              {KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
            </select>
            <div className="builder-params">
              {step.kind === 'classification_change' && (
                <select value={String(step.params.new_classification || 'restricted')}
                  onChange={(e) => setStepParam(i, 'new_classification', e.target.value)}>
                  <option value="sensitive">sensitive</option>
                  <option value="restricted">restricted</option>
                </select>
              )}
              {step.kind === 'new_upstream' && (
                <>
                  <input
                    value={String(step.params.source_urn || '')}
                    onChange={(e) => setStepParam(i, 'source_urn', e.target.value)}
                    placeholder="source URN"
                  />
                  <select value={String(step.params.category || 'third-party')}
                    onChange={(e) => setStepParam(i, 'category', e.target.value)}>
                    <option value="third-party">third-party</option>
                    <option value="unvetted">unvetted</option>
                    <option value="vetted">vetted</option>
                  </select>
                </>
              )}
              {step.kind === 'schema_drift' && (
                <input
                  value={String(step.params.broken_columns || '')}
                  onChange={(e) => setStepParam(i, 'broken_columns', e.target.value.split(',').map((c) => c.trim()).filter(Boolean))}
                  placeholder="broken columns (comma)"
                />
              )}
              {(step.kind !== 'classification_change' && step.kind !== 'new_upstream' && step.kind !== 'schema_drift') && (
                <span style={{ color: 'var(--muted)', fontSize: 12, alignSelf: 'center' }}>—</span>
              )}
            </div>
            <IconButton icon="trash" title="Remove step" className="danger" size={14} onClick={() => setBuilderSteps((s) => s.filter((_, idx) => idx !== i))} disabled={builderSteps.length <= 1} />
          </div>
        ))}
        {builderError && <div className="alert deny">{builderError}</div>}
        {draftNotice && <div className="alert info">{draftNotice}</div>}
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <div className="card">
          <SectionTitle hint="Downstream consumers of a dataset and the agents acting inside the affected subgraph.">
            Dataset blast radius
          </SectionTitle>
          <div className="flow-row">
            <label className="field">
              <span>Dataset</span>
              <select value={blastUrn} onChange={(e) => setBlastUrn(e.target.value)}>
                {entities.map((e) => <option key={e.urn} value={e.urn}>{e.name}</option>)}
              </select>
            </label>
            <label className="field">
              <span>Depth</span>
              <select value={blastDepth} onChange={(e) => setBlastDepth(Number(e.target.value))}>
                {[1, 2, 3, 4, 5].map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </label>
            <IconButton icon="search" title="Analyze blast radius" className="primary" onClick={runBlast} disabled={blastLoading || !blastUrn} />
          </div>
          {blastError && <div className="alert deny">{blastError}</div>}
          {blast && (
            <div style={{ marginTop: 14 }}>
              <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 10 }}>
                <RiskBadge risk={blast.summary.impacted_datasets > 0 ? 'high' : 'low'} />
                <span className="mono" style={{ color: 'var(--muted)', fontSize: 12 }}>
                  {blast.summary.impacted_datasets} downstream · {blast.summary.impacted_agents} agents · depth {blast.summary.max_depth}
                </span>
              </div>
              <ImpactGraph graph={blast.graph} />
              {blast.prediction && (
                <div style={{ marginTop: 12, padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 10, background: 'var(--bg-2)' }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <strong style={{ fontSize: 13 }}>Modeled prediction</strong>
                    <RiskBadge risk={blast.prediction.risk} />
                    <span className="chip">likelihood {blast.prediction.likelihood}</span>
                  </div>
                  <div style={{ fontSize: 13, marginTop: 6 }}>{blast.prediction.summary}</div>
                </div>
              )}
              {(() => {
                const recorded = blast.agents || []
                const predicted = (blast.predicted_agents || []).filter(
                  (p) => !recorded.some((a) => a.agent.agent_id === p.agent.agent_id))
                const all = [...recorded, ...predicted]
                if (!all.length) return <Empty message="No recorded agent actions in this subgraph yet." />
                return (
                  <>
                    <table style={{ marginTop: 12 }}>
                      <thead>
                        <tr><th>agent</th><th>tier</th><th>actions</th><th>count</th><th>weight</th></tr>
                      </thead>
                      <tbody>
                        {all.map((a) => (
                          <tr key={a.agent.agent_id}>
                            <td className="mono">
                              {a.agent.name}
                              {a.predicted && <span className="chip" style={{ marginLeft: 6 }}>Predicted</span>}
                            </td>
                            <td><span className={`badge tier-${a.agent.tier}`}>{cap(a.agent.tier)}</span></td>
                            <td className="mono">{a.actions.join(', ')}</td>
                            <td>{a.count}</td>
                            <td className="mono">{a.weight.toFixed(1)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {predicted.length > 0 && (
                      <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>
                        Agents without recorded actions are predicted from delegations + domain grants.
                      </div>
                    )}
                  </>
                )
              })()}
            </div>
          )}
        </div>

        <div className="card">
          <SectionTitle hint="Every dataset an agent touched plus the consumers those datasets feed.">
            Agent blast radius
          </SectionTitle>
          <div className="flow-row">
            <label className="field">
              <span>Agent</span>
              <select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
                <option value="ag_analyst">kay-analyst</option>
                <option value="ag_engineer">priya-data-engineer</option>
                <option value="ag_ml_engineer">leo-ml-engineer</option>
              </select>
            </label>
            <IconButton icon="search" title="Analyze agent blast radius" className="primary" onClick={runAgentBlast} disabled={agentLoading} />
          </div>
          {agentError && <div className="alert deny">{agentError}</div>}
          {agentBlast && (
            <div style={{ marginTop: 14 }}>
              <div className="mono" style={{ color: 'var(--muted)', fontSize: 12, marginBottom: 10 }}>
                {agentBlast.agent.name} · {agentBlast.datasets.length} datasets touched · {agentBlast.total_actions} actions
              </div>
              <ImpactGraph graph={agentBlast.graph} height={380} />
            </div>
          )}
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <SectionTitle hint="Every what-if and custom experiment is persisted here with its aggregate risk. Open one to re-load its results.">
          Experiment history
        </SectionTitle>
        {experiments.length ? (
          <DataTable
            noMargin
            rows={experiments}
            rowKey={(e) => e.id}
            initialSort="created_at"
            searchPlaceholder="Search experiments…"
            searchText={(e) => `${e.id} ${e.kind} ${e.name || ''} ${e.root_name}`}
            columns={[
              { id: 'id', header: 'id', render: (e) => <span className="mono">{e.id}</span>, sortValue: (e) => e.id },
              { id: 'kind', header: 'kind', render: (e) => (
                <span className="mono">
                  {e.kind}
                  {e.kind === 'custom' && e.name && <div style={{ color: 'var(--muted)', fontSize: 12 }}>{e.name}</div>}
                </span>
              ), sortValue: (e) => e.kind },
              { id: 'dataset', header: 'dataset', render: (e) => <span className="mono">{e.root_name}</span>, sortValue: (e) => e.root_name },
              { id: 'risk', header: 'risk', render: (e) => <RiskBadge risk={e.risk} />, sortValue: (e) => e.risk },
              { id: 'datasets', header: 'impacted datasets', render: (e) => String(e.summary.impacted_datasets ?? 0), sortValue: (e) => Number(e.summary.impacted_datasets ?? 0) },
              { id: 'denied', header: 'denied agents', render: (e) => String(e.summary.denied_agents ?? 0), sortValue: (e) => Number(e.summary.denied_agents ?? 0) },
              { id: 'at', header: 'run at', render: (e) => <span style={{ color: 'var(--muted)', fontSize: 12 }}>{new Date(e.created_at).toLocaleString()}</span>, sortValue: (e) => new Date(e.created_at).getTime() },
              { id: 'view', header: '', render: (e) => <IconButton icon="eye" title="View experiment" size={14} onClick={() => viewExperiment(e.id)} disabled={wiLoading} /> },
            ]}
            empty="No experiments run yet."
          />
        ) : <Empty message="No experiments run yet." />}
      </div>
    </div>
  )
}
