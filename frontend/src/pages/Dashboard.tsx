import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api/client'
import type { DashboardSummary } from '../api/types'
import { PageHeader, Stat, StatusBadge, cap } from '../components/ui'

const TIER_COLORS: Record<string, string> = {
  untrusted: '#94a3b8',
  standard: '#cbd5e1',
  elevated: '#4da1f7',
  privileged: '#a371f7',
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardSummary | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.summary().then(setData).catch((e) => setError(String(e.message || e)))
  }, [])

  if (error) return <div className="alert deny">{error}</div>
  if (!data) return <div className="alert info">Loading dashboard…</div>

  const tierData = Object.entries(data.agents.tiers).map(([name, value]) => ({ name, value }))
  const domainData = Object.entries(data.catalog.by_domain).map(([name, value]) => ({ name, value }))
  const agentDomainData = Object.entries(data.agents.by_domain || {}).map(([name, value]) => ({ name, value }))
  const allowDeny = [
    { name: 'allow', value: data.decisions.allow },
    { name: 'deny', value: data.decisions.deny },
  ]

  return (
    <div>
      <PageHeader
        title="Control Plane Overview"
        subtitle="Zero-trust access, reputation, and tamper-evident audit for agents acting on DataHub."
      />

      <div className="grid cols-4">
        <Stat label="Agents" value={data.agents.total} sub={`${data.agents.active} active`} />
        <Stat label="Active delegations" value={data.delegations.active} sub={`${data.delegations.total} total`} />
        <Stat label="Policy decisions" value={data.decisions.total} sub={`${(data.decisions.deny_rate * 100).toFixed(1)}% denied`} />
        <Stat
          label="Audit chain"
          value={data.chain.valid ? 'valid' : 'TAMPERED'}
          sub={`${data.chain.block_count} blocks · SHA-256`}
        />
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <div className="card">
          <h3>Agent reputation tiers</h3>
          <div style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={tierData} dataKey="value" nameKey="name" innerRadius={50} outerRadius={85} label>
                  {tierData.map((t) => (
                    <Cell key={t.name} fill={TIER_COLORS[t.name]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card">
          <h3>Decisions: allow vs deny</h3>
          <div style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={allowDeny}>
                <XAxis dataKey="name" stroke="var(--muted)" />
                <YAxis stroke="var(--muted)" />
                <Tooltip />
                <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                  <Cell fill="var(--green)" />
                  <Cell fill="var(--red)" />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card">
          <h3>Catalog entities by domain</h3>
          <div style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={domainData} layout="vertical" margin={{ left: 20 }}>
                <XAxis type="number" stroke="var(--muted)" />
                <YAxis type="category" dataKey="name" stroke="var(--muted)" width={90} />
                <Tooltip />
                <Bar dataKey="value" fill="var(--accent)" radius={[0, 6, 6, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {agentDomainData.length > 0 && (
          <div className="card">
            <h3>Agents by granted domain</h3>
            <div style={{ height: 220 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={agentDomainData} layout="vertical" margin={{ left: 20 }}>
                  <XAxis type="number" stroke="var(--muted)" />
                  <YAxis type="category" dataKey="name" stroke="var(--muted)" width={90} />
                  <Tooltip />
                  <Bar dataKey="value" fill="var(--accent-2)" radius={[0, 6, 6, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        <div className="card" style={{ gridColumn: '1 / -1' }}>
          <h3>Recent audit events</h3>
          <table>
            <thead>
              <tr>
                <th>seq</th>
                <th>event</th>
                <th>actor</th>
                <th>decision</th>
                <th>ts</th>
              </tr>
            </thead>
            <tbody>
              {data.recent_events.map((e) => (
                <tr key={e.seq} title={`${e.event_type} · ${e.actor_id} · ${new Date(e.ts).toISOString()}`}>
                  <td className="mono">{e.seq}</td>
                  <td>{e.event_type}</td>
                  <td className="mono">{e.actor_id}</td>
                  <td>{e.decision ? <span className={`badge decision-${e.decision}`}>{cap(e.decision)}</span> : <StatusBadge status="active" />}</td>
                  <td className="mono" style={{ fontSize: 11, color: 'var(--muted)', whiteSpace: 'nowrap' }}>{new Date(e.ts).toLocaleString()}</td>
                </tr>
              ))}
              {data.recent_events.length === 0 && (
                <tr><td colSpan={5} style={{ color: 'var(--muted)' }}>No events yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {data.decisions.top_deny_reasons.length > 0 && (
        <div className="card">
          <h3>Top denial reasons</h3>
          <div className="grid cols-2">
            {data.decisions.top_deny_reasons.map(([reason, count]) => (
              <div key={reason} className="stat">
                <div className="label">{count} denied</div>
                <div style={{ marginTop: 4 }}>{reason}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
