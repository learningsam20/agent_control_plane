import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Agent, Delegation } from '../api/types'
import { DataTable, IconButton, PageHeader, cap } from '../components/ui'

function short(urn: string) {
  const parts = urn.split(',')
  return parts.length > 1 ? parts[1] : urn
}

function fmt(ts: string | null) {
  return ts ? new Date(ts).toLocaleString() : '—'
}

export default function Delegations() {
  const [delegations, setDelegations] = useState<Delegation[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [delegator, setDelegator] = useState('')
  const [delegatee, setDelegatee] = useState('')
  const [actions, setActions] = useState('read,query')
  const [maxDepth, setMaxDepth] = useState(1)
  const [ttl, setTtl] = useState(24)
  const [error, setError] = useState('')
  const [ok, setOk] = useState('')

  const load = () => {
    api.listDelegations().then(setDelegations)
    api.listAgents().then(setAgents)
  }
  useEffect(load, [])

  const create = async () => {
    setError('')
    setOk('')
    try {
      const scope = {
        actions: actions.split(',').map((s) => s.trim()).filter(Boolean),
        datasets: [],
        domains: [],
      }
      const created = await api.createDelegation({
        delegator_id: delegator,
        delegatee_id: delegatee,
        scope,
        max_depth: maxDepth,
        ttl_hours: ttl,
      })
      setOk(`Delegation issued ${created.id}. Capability token (returned once): ${created.token}`)
      load()
    } catch (e) {
      setError(String((e as Error).message || e))
    }
  }

  const revoke = async (id: string) => {
    await api.revokeDelegation(id)
    load()
  }

  const name = (id: string) => agents.find((a) => a.id === id)?.name || id

  return (
    <div>
      <PageHeader
        title="Delegations"
        subtitle="A delegator vouches for a delegatee within an exact scope (actions · datasets · domains) and a bounded chain depth. Delegated actions reflect on the delegator's reputation."
      />

      <div className="card">
        <h3>Issue a delegation</h3>
        <div className="flow-row">
          <label className="field">
            <span>Delegator (vouches)</span>
            <select value={delegator} onChange={(e) => setDelegator(e.target.value)}>
              <option value="">select…</option>
              {agents.map((a) => <option key={a.id} value={a.id}>{a.name} · {a.tier}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Delegatee (acts)</span>
            <select value={delegatee} onChange={(e) => setDelegatee(e.target.value)}>
              <option value="">select…</option>
              {agents.map((a) => <option key={a.id} value={a.id}>{a.name} · {a.tier}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Actions (comma separated)</span>
            <input value={actions} onChange={(e) => setActions(e.target.value)} />
          </label>
          <label className="field">
            <span>Max depth</span>
            <input type="number" min={1} max={3} value={maxDepth} onChange={(e) => setMaxDepth(Number(e.target.value))} />
          </label>
          <label className="field">
            <span>TTL hours</span>
            <input type="number" min={1} value={ttl} onChange={(e) => setTtl(Number(e.target.value))} />
          </label>
          <IconButton icon="send" title="Issue delegation" className="primary" onClick={create} disabled={!delegator || !delegatee} />
        </div>
        {error && <div className="alert deny">{error}</div>}
        {ok && <div className="alert allow">{ok}</div>}
      </div>

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <h3 style={{ padding: '14px 16px 0', marginBottom: 0 }}>
          Delegations <span className="chip">token-validity based — each row is an independent capability token</span>
        </h3>
        <DataTable
          noMargin
          rows={delegations}
          rowKey={(d) => d.id}
          initialSort="issued_at"
          searchPlaceholder="Search delegations…"
          searchText={(d) => `${d.id} ${name(d.delegator_id)} ${name(d.delegatee_id)} ${(d.scope.actions || []).join(' ')} ${(d.scope.domains || []).join(' ')} ${d.status}`}
          columns={[
            { id: 'id', header: 'id', render: (d) => <span className="mono">{d.id}</span>, sortValue: (d) => d.id },
            { id: 'delegator', header: 'delegator', render: (d) => name(d.delegator_id), sortValue: (d) => d.delegator_id },
            { id: 'delegatee', header: 'delegatee', render: (d) => name(d.delegatee_id), sortValue: (d) => d.delegatee_id },
            { id: 'scope', header: 'scope', sortValue: (d) => (d.scope.actions || []).join(','), render: (d) => (
              <div style={{ fontSize: 12 }}>
                {(d.scope.actions || []).join(', ')}
                {(d.scope.datasets || []).length > 0 && (
                  <div className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>{(d.scope.datasets || []).map(short).join(', ')}</div>
                )}
                {(d.scope.domains || []).length > 0 && (
                  <div className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>domain: {(d.scope.domains || []).join(', ')}</div>
                )}
              </div>
            ) },
            { id: 'depth', header: 'depth', render: (d) => <span className="mono">{d.depth}/{d.max_depth}</span>, sortValue: (d) => d.depth },
            { id: 'status', header: 'validity', sortValue: (d) => d.status, render: (d) => (
              <span className={`badge ${d.status === 'active' ? 'status-active' : d.status === 'expired' ? 'status-expired' : 'status-revoked'}`}>{cap(d.status)}</span>
            ) },
            { id: 'issued', header: 'issued', render: (d) => <span style={{ fontSize: 12, color: 'var(--muted)' }}>{fmt(d.issued_at)}</span>, sortValue: (d) => d.issued_at ?? '' },
            { id: 'expires', header: 'expires', render: (d) => <span style={{ fontSize: 12, color: 'var(--muted)' }}>{fmt(d.expires_at)}</span>, sortValue: (d) => d.expires_at ?? '' },
            { id: 'revoke', header: '', sortValue: (d) => d.status, render: (d) => d.status === 'active' && <IconButton icon="ban" size={14} title="Revoke delegation" className="danger" onClick={() => revoke(d.id)} /> },
          ]}
          footer={
            <p style={{ color: 'var(--muted)', fontSize: 12, margin: 0, padding: '10px 16px', borderTop: '1px solid var(--border)' }}>
              <span className="badge status-active">Active</span> usable now ·{' '}
              <span className="badge status-expired">Expired</span> past its TTL — the gateway rejects it ·{' '}
              <span className="badge status-revoked">Revoked</span> explicitly withdrawn (audited). Revoking or expiring one token does not affect any other.
            </p>
          }
          empty="No delegations yet"
        />
      </div>
    </div>
  )
}
