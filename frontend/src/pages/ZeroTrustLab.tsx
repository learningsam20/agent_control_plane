import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { PageHeader, IconButton, InfoTip, cap } from '../components/ui'
import type {
  Agent,
  ScenarioBlueprint,
  ScenarioDef,
  ScenarioExecution,
  ScenarioPreview,
  ScenarioTransformResult,
} from '../api/types'

function short(urn: string) {
  const parts = urn.split(',')
  return parts.length > 1 ? parts[1] : urn
}

function PolicyList({ blueprint }: { blueprint: ScenarioBlueprint }) {
  if (!blueprint.policies.length) {
    return <p style={{ color: 'var(--muted)' }}>No new policies generated — the seed policies already govern this scenario.</p>
  }
  return (
    <div>
      {blueprint.policies.map((p) => (
        <div key={p.name} className="card" style={{ marginBottom: 8, padding: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className={`badge decision-${p.effect}`} style={{ textTransform: 'uppercase' }}>{p.effect}</span>
            <strong className="mono">{p.name}</strong>
            <span className="chip" style={{ marginLeft: 'auto' }}>order {p.order}</span>
          </div>
          <p style={{ color: 'var(--muted)', margin: '6px 0 0', fontSize: 12 }}>{p.description}</p>
          <div style={{ marginTop: 6 }}>
            {p.actions.map((a) => <span key={a} className="chip">{a}</span>)}
            {p.conditions.map((c, i) => <span key={i} className="chip">{`${c.path} ${c.op} ${JSON.stringify(c.value ?? c.ref ?? '')}`}</span>)}
          </div>
        </div>
      ))}
    </div>
  )
}

export default function ZeroTrustLab() {
  const [scenarios, setScenarios] = useState<ScenarioDef[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [mode, setMode] = useState<'predefined' | 'custom'>('predefined')
  const [selectedId, setSelectedId] = useState('')
  const [objective, setObjective] = useState('')
  const [selectedAgents, setSelectedAgents] = useState<string[]>([])
  const [plan, setPlan] = useState<ScenarioTransformResult | null>(null)
  const [preview, setPreview] = useState<ScenarioPreview | null>(null)
  const [execution, setExecution] = useState<ScenarioExecution | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    api.listScenarios().then((s) => {
      setScenarios(s)
      if (s.length) {
        setSelectedId(s[0].id)
        setObjective(s[0].objective)
      }
    }).catch((e) => setError(String((e as Error).message || e)))
    api.listAgents().then(setAgents).catch(() => {})
  }, [])

  const clearResults = () => { setPlan(null); setPreview(null); setExecution(null); setNotice('') }

  const pickScenario = (id: string) => {
    setSelectedId(id)
    const s = scenarios.find((x) => x.id === id)
    if (s) { setObjective(s.objective); clearResults() }
  }

  const transform = async () => {
    setBusy('transform'); setError('')
    try {
      const result = await api.transformScenario({
        scenario_id: mode === 'predefined' ? selectedId : '',
        objective: mode === 'custom' ? objective : '',
        agents: mode === 'custom' ? selectedAgents : undefined,
      })
      setPlan(result); setPreview(null); setExecution(null); setNotice('')
    } catch (e) { setError(String((e as Error).message || e)) } finally { setBusy('') }
  }

  const previewPlan = async () => {
    if (!plan) return
    setBusy('preview'); setError('')
    try { setPreview(await api.previewScenario(plan.plan_id)) }
    catch (e) { setError(String((e as Error).message || e)) } finally { setBusy('') }
  }

  const approve = async () => {
    if (!plan) return
    setBusy('approve'); setError('')
    try {
      const exec = await api.approveScenario(plan.plan_id)
      setExecution(exec); setNotice('Plan approved — generated policies persisted, delegation issued, steps enforced.')
    } catch (e) { setError(String((e as Error).message || e)) } finally { setBusy('') }
  }

  const reject = async () => {
    if (!plan) return
    setBusy('reject'); setError('')
    try {
      await api.rejectScenario(plan.plan_id)
      setNotice('Plan rejected — nothing was persisted.')
      clearResults()
    } catch (e) { setError(String((e as Error).message || e)) } finally { setBusy('') }
  }

  const reset = async () => {
    setBusy('reset'); setError('')
    try {
      const r = await api.resetLab()
      setNotice(`Lab reset — removed ${r.policies_removed} lab-generated policies, restored demo agents.`)
      clearResults()
    } catch (e) { setError(String((e as Error).message || e)) } finally { setBusy('') }
  }

  const blueprint = plan?.blueprint
  const agentName = (id: string) => agents.find((a) => a.id === id)?.name || id

  return (
    <div>
      <PageHeader
        title="Zero-Trust Lab"
        subtitle="Define a scenario, let the planner transform it into agentic steps, policies and delegations, simulate them in preview, then approve to enforce through the signed gateway."
        actions={<IconButton icon="reset" title="Reset lab" onClick={reset} disabled={!!busy} />}
      />

      {error && <div className="alert deny">{error}</div>}
      {notice && <div className="alert info">{notice}</div>}

      {/* 1 · define */}
      <div className="card">
        <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          1 · Define the scenario
          <InfoTip text="Pick a bundled scenario or describe a custom situation in natural language. The planner turns it into agentic steps, governance policies, and a scoped delegation — nothing is persisted until you approve." />
        </h3>
        <div className="flow-row" style={{ marginBottom: 12 }}>
          <button className={mode === 'predefined' ? 'primary' : ''} onClick={() => { setMode('predefined'); clearResults() }}>Bundled scenario</button>
          <button className={mode === 'custom' ? 'primary' : ''} onClick={() => { setMode('custom'); clearResults() }}>Custom scenario</button>
        </div>

        {mode === 'predefined' ? (
          <>
            <label className="field">
              <span>Scenario</span>
              <select value={selectedId} onChange={(e) => pickScenario(e.target.value)}>
                {scenarios.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </label>
            {(() => {
              const s = scenarios.find((x) => x.id === selectedId)
              return s ? (
                <>
                  <p style={{ color: 'var(--muted)', margin: '0 0 8px' }}>{s.description}</p>
                  <div className="mono-block">{s.objective}</div>
                </>
              ) : null
            })()}
          </>
        ) : (
          <>
            <label className="field">
              <span>Objective (describe the situation in natural language)</span>
              <textarea rows={5} value={objective} onChange={(e) => { setObjective(e.target.value); clearResults() }} placeholder="e.g. The analyst should read the restricted patient billing mart after the engineer delegates scoped access, but must never be able to write to it." />
            </label>
            <label className="field">
              <span>Constrain agents (optional)</span>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {agents.filter((a) => a.id.startsWith('ag_')).map((a) => {
                  const on = selectedAgents.includes(a.id)
                  return (
                    <button key={a.id} className={on ? 'primary' : ''} onClick={() => {
                      setSelectedAgents(on ? selectedAgents.filter((x) => x !== a.id) : [...selectedAgents, a.id])
                      clearResults()
                    }}>{a.name}</button>
                  )
                })}
              </div>
            </label>
          </>
        )}

        <IconButton icon="zap" title="Transform into an agentic plan" className="primary" onClick={transform} disabled={!!busy || (mode === 'custom' && !objective.trim())} />
      </div>

      {/* 2 · review */}
      {blueprint && (
        <div className="card">
          <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            2 · Review the transformed plan
            <InfoTip text="The planner derives agentic steps, governance policies, and a scoped delegation from the objective. Nothing is persisted until you approve." />
            <span className={`badge status-${plan!.status === 'proposed' ? 'active' : ''}`}>{cap(plan!.status)}</span>
          </h3>
          <p style={{ color: 'var(--muted)', margin: '0 0 10px' }}>
            <strong>{blueprint.steps.length} agentic steps</strong> across{' '}
            <strong>{blueprint.agents.length} agent{blueprint.agents.length > 1 ? 's' : ''}</strong>{' '}
            {blueprint.policies.length ? <>and <strong>{blueprint.policies.length} governance policies</strong></> : null}
            {blueprint.delegation ? ' plus a scoped delegation' : ''}.
          </p>

          <h4>Agentic actions</h4>
          <table>
            <thead><tr><th>#</th><th>agent</th><th>action</th><th>resource</th><th>delegation</th><th>note</th></tr></thead>
            <tbody>
              {blueprint.steps.map((s, i) => (
                <tr key={i}>
                  <td>{i + 1}</td>
                  <td>{agentName(s.agent)}</td>
                  <td><span className="chip">{s.action}</span></td>
                  <td className="mono" style={{ fontSize: 11 }}>{short(s.resource)}</td>
                  <td>{s.delegation ? <span className={`badge status-active`}>yes</span> : '—'}</td>
                  <td style={{ fontSize: 12, color: 'var(--muted)' }}>{s.note || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h4 style={{ marginTop: 14 }}>Generated policies</h4>
          <PolicyList blueprint={blueprint} />

          {blueprint.delegation && (
            <>
              <h4 style={{ marginTop: 14 }}>Scoped delegation</h4>
              <div className="mono-block">
                {agentName(blueprint.delegation.delegator_id)} → {agentName(blueprint.delegation.delegatee_id)} · max depth {blueprint.delegation.max_depth}<br />
                scope: actions [{blueprint.delegation.scope.actions?.join(', ')}] · datasets [{blueprint.delegation.scope.datasets?.map(short).join(', ')}]
              </div>
            </>
          )}

          <div className="flow-row" style={{ marginTop: 14 }}>
            <IconButton icon="activity" title="Simulate policies (preview)" className="primary" onClick={previewPlan} disabled={!!busy} />
            <IconButton icon="check" title="Approve & enforce" className="primary" onClick={approve} disabled={!!busy} />
            <IconButton icon="ban" title="Reject" className="danger" onClick={reject} disabled={!!busy} />
          </div>
        </div>
      )}

      {/* 3 · preview */}
      {preview && (
        <div className="card">
          <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            3 · Policy simulation
            <InfoTip text="Each step was evaluated against the current seed policies plus the proposed generated policies, exactly as the gateway would decide after approval. In-memory — nothing persisted." />
            <span className="chip">in-memory · nothing persisted</span>
          </h3>
          <table>
            <thead><tr><th>#</th><th>agent</th><th>action</th><th>resource</th><th>predicted</th><th>policy</th><th>expected</th></tr></thead>
            <tbody>
              {preview.predictions.map((p) => (
                <tr key={p.index}>
                  <td>{p.index + 1}</td>
                  <td>{agentName(p.agent)}</td>
                  <td><span className="chip">{p.action}</span></td>
                  <td className="mono" style={{ fontSize: 11 }}>{p.resource_name}</td>
                  <td>
                    <span className={`badge decision-${p.predicted}`} style={{ textTransform: 'uppercase' }}>{p.predicted}</span>
                    {p.expected && (p.predicted === p.expected
                      ? <span className="chip" style={{ marginLeft: 6, color: 'var(--green)' }}>✓ as intended</span>
                      : <span className="chip" style={{ marginLeft: 6, color: 'var(--red)' }}>⚠ differs from expected</span>)}
                  </td>
                  <td style={{ fontSize: 12 }}>
                    <span className="mono">{p.policy}</span>
                    {p.policy_generated && <span className="chip" style={{ marginLeft: 6, color: 'var(--teal)' }}>generated</span>}
                  </td>
                  <td className="mono" style={{ fontSize: 11 }}>{p.expected ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {preview.predictions.some((p) => p.policy_generated) && (
            <p style={{ color: 'var(--muted)', marginTop: 10, fontSize: 12 }}>
              Decisions highlighted by the <span className="chip" style={{ color: 'var(--teal)' }}>generated</span> badge are governed by policies this plan would create on approval.
            </p>
          )}
        </div>
      )}

      {/* 4 · enforcement */}
      {execution && (
        <div className="card">
          <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            4 · Enforcement result <span className={`badge decision-allow`}>Approved & executed</span>
            <InfoTip text="On approval, generated policies are persisted and enabled and the scoped delegation is issued. Every step is then re-run through the real signed gateway and audited into the tamper-evident chain." />
          </h3>
          <div style={{ marginBottom: 10 }}>
            {execution.policies_created.map((p) => <span key={p} className="chip">{p}</span>)}
            <span className="chip">persisted & enabled</span>
          </div>
          {execution.delegation && (
            <div className="mono-block" style={{ marginBottom: 10 }}>
              delegation: {execution.delegation.id}<br />
              capability token: {execution.delegation.token}
            </div>
          )}
          <table>
            <thead><tr><th>#</th><th>agent</th><th>action</th><th>resource</th><th>decision</th><th>policy / reason</th><th>audit</th><th>expected</th></tr></thead>
            <tbody>
              {execution.steps.map((s) => {
                const ok = !s.expected || s.decision === s.expected
                return (
                  <tr key={s.index}>
                    <td>{s.index + 1}</td>
                    <td>{agentName(s.agent)}</td>
                    <td><span className="chip">{s.action}</span>{s.delegation && <span className="chip" style={{ color: 'var(--teal)' }}>via delegation</span>}</td>
                    <td className="mono" style={{ fontSize: 11 }}>{short(s.resource)}</td>
                    <td><span className={`badge decision-${s.decision}`} style={{ textTransform: 'uppercase' }}>{s.decision}</span></td>
                    <td style={{ fontSize: 12 }}>{s.policy || s.reason}</td>
                    <td className="mono" style={{ fontSize: 11 }}>{s.audit_seq ?? '—'}</td>
                    <td>
                      {s.expected
                        ? <span className={`chip`} style={{ color: ok ? 'var(--green)' : 'var(--red)' }}>{s.expected}{ok ? ' ✓' : ' ✗'}</span>
                        : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <p style={{ color: 'var(--muted)', marginTop: 10, fontSize: 12 }}>
            Every step was a genuine Ed25519-signed gateway request, appended to the tamper-evident audit chain, and reflected back on each agent's reputation.
          </p>
        </div>
      )}

      {!blueprint && !error && (
        <div className="card" style={{ color: 'var(--muted)', display: 'flex', gap: 8, alignItems: 'center' }}>
          <InfoTip text="Pick a bundled scenario or write your own. The planner turns it into concrete agentic actions plus the policies and delegations needed to govern them — you review and approve before anything is enforced." />
          <span>Pick a bundled scenario or write your own to begin.</span>
        </div>
      )}
    </div>
  )
}
