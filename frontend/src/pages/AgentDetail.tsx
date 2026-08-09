import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import type { Agent, DataHubEntity, Delegation, GatewayResponse } from '../api/types'
import { DecisionBadge, PageHeader, ScoreBar, StatusBadge, TierBadge, cap } from '../components/ui'

type Tab = 'overview' | 'delegations' | 'actions'

export default function AgentDetail() {
  const { id = '' } = useParams()
  const [agent, setAgent] = useState<Agent | null>(null)
  const [timeline, setTimeline] = useState<Array<{ ts: string; score: number; tier: string }>>([])
  const [delegations, setDelegations] = useState<Delegation[]>([])
  const [actions, setActions] = useState<DataHubEntity[]>([])
  const [history, setHistory] = useState<GatewayResponse[]>([])
  const [tab, setTab] = useState<Tab>('overview')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!id) return
    Promise.all([
      api.getAgent(id),
      api.reputation(id),
      api.listDelegations(),
      api.entities(),
    ])
      .then(([a, rep, dl, ents]) => {
        setAgent(a)
        setTimeline((rep.timeline as Array<{ ts: string; delta: number; score: number; tier: string }>) || [])
        const relevant = dl.filter((d) => d.delegator_id === id || d.delegatee_id === id)
        setDelegations(relevant)
        setActions(ents)
      })
      .catch((e) => setError(String(e.message || e)))

    api.listAudit({ agent_id: id, limit: 50 }).then((evts) => {
      setHistory(
        evts
          .filter((e) => e.event_type.startsWith('request'))
          .map((e) => ({
            request_id: String(e.payload.request_id || e.id),
            decision: (e.decision as 'allow' | 'deny') || 'deny',
            reason: String(e.payload.reason || e.event_type),
            policy_name: String(e.payload.policy || e.event_type),
            engine: 'native',
            agent_id: id,
            event_id: e.id,
            audit_seq: e.seq,
          })),
      )
    })
  }, [id])

  if (error) return <div className="alert deny">{error}</div>
  if (!agent) return <div className="alert info">Loading agent…</div>

  const agentIdForImpact = agent.id

  return (
    <div>
      <PageHeader
        title={agent.name}
        subtitle={
          <span>
            <span className="mono">{agent.id}</span> · {agent.description}
          </span>
        }
      />

      <div className="grid cols-4">
        <div className="stat"><div className="label">Tier</div><div style={{ marginTop: 6 }}><TierBadge tier={agent.tier} /></div></div>
        <div className="stat"><div className="label">Status</div><div style={{ marginTop: 6 }}><StatusBadge status={agent.status} /></div></div>
        <div className="stat"><div className="label">Domains</div><div style={{ marginTop: 6 }}>{agent.granted_domains.join(', ')}</div></div>
        <div className="stat"><div className="label">Trust score</div><div style={{ marginTop: 8 }}><ScoreBar score={agent.trust_score} /></div></div>
      </div>

      <div style={{ display: 'flex', gap: 8, margin: '18px 0' }}>
        {(['overview', 'delegations', 'actions'] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? 'primary' : ''} onClick={() => setTab(t)} style={{ textTransform: 'capitalize' }}>
            {t}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <>
          <div className="grid cols-2">
            <div className="card">
              <h3>Trust score timeline</h3>
              <div style={{ height: 260 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={timeline}>
                    <XAxis dataKey="ts" stroke="var(--muted)" tick={{ fontSize: 10 }} />
                    <YAxis domain={[0, 100]} stroke="var(--muted)" />
                    <Tooltip />
                    <Line type="monotone" dataKey="score" stroke="var(--accent)" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {timeline.length === 0 && <p style={{ color: 'var(--muted)' }}>No reputation events yet — make requests to build history.</p>}
            </div>

            <div className="card">
              <h3>Recent request history</h3>
              <table>
                <thead><tr><th>action</th><th>decision</th><th>reason</th></tr></thead>
                <tbody>
                  {history.map((h) => (
                    <tr key={h.event_id}>
                      <td className="mono">{h.reason.length > 40 ? `${h.reason.slice(0, 40)}…` : h.reason}</td>
                      <td><DecisionBadge decision={h.decision} /></td>
                      <td className="mono">{h.audit_seq}</td>
                    </tr>
                  ))}
                  {history.length === 0 && <tr><td colSpan={3} style={{ color: 'var(--muted)' }}>No requests yet</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {tab === 'delegations' && (
        <div className="card">
          <h3>Delegations involving this agent</h3>
          <table>
            <thead>
              <tr><th>id</th><th>delegator</th><th>delegatee</th><th>scope</th><th>depth</th><th>status</th></tr>
            </thead>
            <tbody>
              {delegations.map((d) => (
                <tr key={d.id}>
                  <td className="mono">{d.id}</td>
                  <td className="mono">{d.delegator_id}</td>
                  <td className="mono">{d.delegatee_id}</td>
                  <td>{[...(d.scope.actions || [])].join(', ')}</td>
                  <td className="mono">{d.depth}/{d.max_depth}</td>
                  <td>{d.active ? <span className="badge status-active">Active</span> : <span className="badge status-revoked">Inactive</span>}</td>
                </tr>
              ))}
              {delegations.length === 0 && <tr><td colSpan={6} style={{ color: 'var(--muted)' }}>No delegations</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'actions' && (
        <div className="card">
          <h3>DataHub impact preview</h3>
          <p style={{ color: 'var(--muted)' }}>
            Full impact matrix for <span className="mono">{agentIdForImpact}</span> is on the DataHub page (heatmap).
          </p>
          <table>
            <thead>
              <tr><th>entity</th><th>domain</th><th>classification</th></tr>
            </thead>
            <tbody>
              {actions.slice(0, 12).map((e) => (
                <tr key={e.urn}>
                  <td className="mono">{e.name}</td>
                  <td>{e.domain}</td>
                  <td><span className={`badge classification-${e.data_classification}`}>{cap(e.data_classification)}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
