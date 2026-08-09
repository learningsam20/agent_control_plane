import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Agent, AgentRun } from '../api/types'
import { DataTable, Empty, IconButton, PageHeader, cap } from '../components/ui'

const RUN_LABEL: Record<string, string> = {
  pending: 'pending',
  running: 'running…',
  succeeded: 'succeeded',
  denied: 'denied',
  failed: 'failed',
}

function short(urn: string) {
  const parts = urn.split(',')
  return parts.length > 1 ? parts[1] : urn
}

function RunDetail({ run }: { run: AgentRun }) {
  return (
    <div>
      <div className="mono" style={{ color: 'var(--muted)', fontSize: 11, marginBottom: 8 }}>trace {run.trace_id}</div>
      {run.plan.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          {run.plan.map((p, i) => (
            <span key={i} className="chip">{p.action} {short(p.resource)}</span>
          ))}
        </div>
      )}

      {run.results.length > 0 && (
        <table className="table">
          <thead>
            <tr><th>action</th><th>resource</th><th>decision</th><th>policy / reason</th><th>audit</th></tr>
          </thead>
          <tbody>
            {run.results.map((r, i) => (
              <tr key={i}>
                <td><span className="chip">{r.action}</span></td>
                <td className="mono" style={{ fontSize: 11 }}>{short(r.resource)}</td>
                <td><span className={`badge decision-${r.decision}`}>{cap(r.decision)}</span></td>
                <td style={{ fontSize: 12 }}>{r.policy || r.reason}</td>
                <td className="mono" style={{ fontSize: 11 }}>{r.audit_seq ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {run.summary && <pre className="mono-block" style={{ marginTop: 10 }}>{run.summary}</pre>}
    </div>
  )
}

export default function AgentRuns() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [runs, setRuns] = useState<AgentRun[]>([])
  const [agentId, setAgentId] = useState('ag_analyst')
  const [objective, setObjective] = useState('Read the patient demographics mart and report on the patient population')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const refresh = () => api.listRuns().then(setRuns).catch((e) => setError(String(e.message || e)))

  useEffect(() => {
    api.listAgents().then((a) => {
      setAgents(a)
      const active = a.find((x) => x.status === 'active')
      if (active) setAgentId(active.id)
    }).catch((e) => setError(String(e.message || e)))
    refresh()
  }, [])

  const run = async () => {
    setBusy(true)
    setError('')
    try {
      await api.runAgent(agentId, objective, true)
      await refresh()
    } catch (e) {
      setError(String((e as Error).message || e))
    } finally {
      setBusy(false)
    }
  }

  const resetDemo = async () => {
    setError('')
    try {
      const res = await fetch(`${import.meta.env.VITE_API_URL || ''}/api/demo/reset`, { method: 'POST' })
      if (!res.ok) throw new Error(await res.text())
      await refresh()
    } catch (e) {
      setError(String((e as Error).message || e))
    }
  }

  return (
    <div>
      <PageHeader
        title="Agent Runs"
        subtitle="Give a governed LangGraph agent an objective. The planner builds a plan, the executor acts only through the signed gateway, and every decision is audited and fed into reputation."
        actions={<IconButton icon="reset" title="Reset demo agents" onClick={resetDemo} />}
      />

      {error && <div className="alert deny">{error}</div>}

      <div className="card">
        <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr auto', gap: 10, alignItems: 'center' }}>
          <select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>{a.name} ({a.status})</option>
            ))}
          </select>
          <input
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            placeholder="e.g. Read the restricted patient billing mart"
          />
          <IconButton icon="play" title="Run agent" className="primary" onClick={run} disabled={busy || !objective.trim()} />
        </div>
        <p style={{ color: 'var(--muted)', fontSize: 12, marginTop: 8 }}>
          Try: “Read the patient demographics mart and report on it” (allowed) vs
          “Read the restricted patient billing mart” (denied — restricted data needs a privileged tier).
        </p>
      </div>

      {runs.length === 0 ? (
        <Empty message="No runs yet — give an agent an objective above." />
      ) : (
        <DataTable
          rows={runs}
          rowKey={(r) => r.id}
          initialSort="created_at"
          searchPlaceholder="Search runs by agent, objective, status…"
          searchText={(r) => `${r.id} ${r.agent_id} ${r.objective} ${r.status} ${r.summary}`}
          expandRender={(r) => <RunDetail run={r} />}
          columns={[
            { id: 'id', header: 'run', render: (r) => <span className="mono">{r.id}</span>, sortValue: (r) => r.id },
            { id: 'agent', header: 'agent', render: (r) => <span className="mono">{r.agent_id}</span>, sortValue: (r) => r.agent_id },
            { id: 'objective', header: 'objective', render: (r) => <span style={{ fontWeight: 600 }}>{r.objective}</span>, sortValue: (r) => r.objective },
            { id: 'status', header: 'status', render: (r) => <span className="badge" style={{ textTransform: 'uppercase' }}>{RUN_LABEL[r.status] || r.status}</span>, sortValue: (r) => r.status },
            { id: 'steps', header: 'steps', render: (r) => <span className="mono">{r.results.length}</span>, sortValue: (r) => r.results.length },
            { id: 'created_at', header: 'at', render: (r) => <span style={{ color: 'var(--muted)', fontSize: 12 }}>{new Date(r.created_at).toLocaleString()}</span>, sortValue: (r) => new Date(r.created_at).getTime() },
          ]}
          empty="No runs yet."
        />
      )}
    </div>
  )
}
