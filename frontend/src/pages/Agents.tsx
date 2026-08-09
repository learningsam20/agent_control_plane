import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { Agent } from '../api/types'
import { DataTable, IconButton, PageHeader, ScoreBar, StatusBadge, TierBadge } from '../components/ui'

export default function Agents() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    api.listAgents().then(setAgents).catch((e) => setError(String(e.message || e)))
  }, [])

  const changeStatus = async (id: string, status: string) => {
    await api.setAgentStatus(id, status)
    setAgents(await api.listAgents())
  }

  return (
    <div>
      <PageHeader
        title="Agents"
        subtitle="Every agent holds an Ed25519 identity. Reputation tiers gate what they may do; all actions are signed and chained in the audit log."
        actions={
          <Link to="/agents/register" title="Onboard agent"><IconButton icon="plus" title="Onboard agent" /></Link>
        }
      />

      {error && <div className="alert deny">{error}</div>}

      <DataTable
        noMargin
        rows={agents}
        rowKey={(a) => a.id}
        initialSort="name"
        searchPlaceholder="Search agents…"
        searchText={(a) => `${a.name} ${a.id} ${a.granted_domains.join(' ')} ${a.status}`}
        columns={[
          { id: 'name', header: 'name', sortValue: (a) => a.name, render: (a) => (
            <Link to={`/agents/${a.id}`} style={{ color: 'var(--text)', fontWeight: 600, textDecoration: 'none' }}>
              {a.name}
            </Link>
          ) },
          { id: 'tier', header: 'tier', sortValue: (a) => a.tier, render: (a) => <TierBadge tier={a.tier} /> },
          { id: 'status', header: 'status', sortValue: (a) => a.status, render: (a) => <StatusBadge status={a.status} /> },
          { id: 'domains', header: 'domains', sortValue: (a) => a.granted_domains.join(','), render: (a) => a.granted_domains.map((d) => <span key={d} className="chip">{d}</span>) },
          { id: 'trust_score', header: 'trust score', sortValue: (a) => a.trust_score, render: (a) => <ScoreBar score={a.trust_score} /> },
          { id: 'actions', header: 'actions', sortValue: (a) => a.status, render: (a) => (
            a.status === 'active' ? (
              <div style={{ display: 'flex', gap: 6 }}>
                <IconButton icon="pause" size={14} title="Suspend" onClick={() => changeStatus(a.id, 'suspended')} />
                <IconButton icon="ban" size={14} title="Revoke" className="danger" onClick={() => changeStatus(a.id, 'revoked')} />
              </div>
            ) : (
              <IconButton icon="activate" size={14} title="Activate" onClick={() => changeStatus(a.id, 'active')} />
            )
          ) },
        ]}
        empty="No agents onboarded yet"
      />
    </div>
  )
}
