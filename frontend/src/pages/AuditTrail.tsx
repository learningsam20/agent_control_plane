import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AuditEvent, AuditTrace, ChainVerify, TamperResult } from '../api/types'
import { DecisionBadge, DataTable, Empty, IconButton, PageHeader, cap } from '../components/ui'

const short = (h: string) => (h ? `${h.slice(0, 10)}…` : '—')
const shortUrn = (urn: string) => {
  const parts = urn.split(',')
  return parts.length > 1 ? parts[1] : urn
}

function download(text: string, filename: string, mime: string) {
  const blob = new Blob([text], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export default function AuditTrail() {
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [chain, setChain] = useState<ChainVerify | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filters, setFilters] = useState({ event_type: '', agent_id: '', decision: '', limit: 200 })
  const [tampering, setTampering] = useState(false)
  const [repairing, setRepairing] = useState(false)
  const [tamperResult, setTamperResult] = useState<TamperResult | null>(null)
  const [exporting, setExporting] = useState<'csv' | 'json' | ''>('')
  const [traces, setTraces] = useState<Record<number, AuditTrace | null>>({})
  const [traceLoading, setTraceLoading] = useState<number | null>(null)
  const [traceError, setTraceError] = useState<Record<number, string>>({})

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [evts, ch] = await Promise.all([
        api.listAudit(filters),
        api.verifyChain(),
      ])
      setEvents(evts)
      setChain(ch)
    } catch (e) {
      setError(String((e as Error).message || e))
    } finally {
      setLoading(false)
    }
  }, [filters])

  useEffect(() => { load() }, [load])

  const tamper = async () => {
    setTampering(true)
    setTamperResult(null)
    try {
      const res = await api.simulateTamper()
      setTamperResult(res)
      await load()
    } catch (e) {
      setError(String((e as Error).message || e))
    } finally {
      setTampering(false)
    }
  }

  const repair = async () => {
    setRepairing(true)
    try {
      await api.repairChain()
      setTamperResult(null)
      await load()
    } catch (e) {
      setError(String((e as Error).message || e))
    } finally {
      setRepairing(false)
    }
  }

  const doExport = async (format: 'csv' | 'json') => {
    setExporting(format)
    try {
      const text = await api.exportAudit(format)
      download(text, `audit-trail.${format}`, format === 'csv' ? 'text/csv' : 'application/json')
    } catch (e) {
      setError(String((e as Error).message || e))
    } finally {
      setExporting('')
    }
  }

  const loadTrace = async (seq: number, eventId: string) => {
    setTraceLoading(seq)
    setTraceError((p) => ({ ...p, [seq]: '' }))
    try {
      const trace = await api.auditTrace(eventId)
      setTraces((p) => ({ ...p, [seq]: trace }))
    } catch (e) {
      setTraceError((p) => ({ ...p, [seq]: String((e as Error).message || e) }))
    } finally {
      setTraceLoading(null)
    }
  }

  const issueCount = chain?.issues?.length ?? 0

  return (
    <div>
      <PageHeader
        title="Audit Trail"
        subtitle="Every gateway decision is appended to a hash-chained ledger with Ed25519 signatures. Recompute hashes to prove nothing was altered."
      />

      <div className="card grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        <div>
          <div className="label">Blocks</div>
          <div className="value">{chain?.block_count ?? '—'}</div>
        </div>
        <div>
          <div className="label">Chain integrity</div>
          <div className="value" style={{ color: chain?.valid ? 'var(--green)' : 'var(--red)' }}>
            {chain == null ? '—' : chain.valid ? 'VALID' : 'TAMPERED'}
          </div>
        </div>
        <div>
          <div className="label">Integrity issues</div>
          <div className="value" style={{ color: issueCount ? 'var(--red)' : 'inherit' }}>{issueCount}</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8 }}>
          <IconButton icon="wrench" title="Simulate tamper" className="danger" onClick={tamper} disabled={tampering} />
          <IconButton icon="download" title="Export CSV" onClick={() => doExport('csv')} disabled={Boolean(exporting)} />
          <IconButton icon="download" title="Export JSON" onClick={() => doExport('json')} disabled={Boolean(exporting)} />
        </div>
      </div>

      {tamperResult?.agent_run && (
        <div className="card" style={{ marginTop: 12, borderLeft: '4px solid var(--amber)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
            <strong>A governed agent ran first — then its audit block was tampered with</strong>
            <span className="badge decision-deny" style={{ textTransform: 'uppercase' }}>seq {tamperResult.seq}</span>
          </div>
          <p style={{ color: 'var(--muted)', margin: '8px 0 0' }}>
            {tamperResult.agent_run.objective} — plan drafted by the {tamperResult.agent_run.plan_source} planner
            ({tamperResult.agent_run.plan.length} action(s), {tamperResult.agent_run.status}). The block hash was not
            recomputed, so chain verification now flags it.
          </p>
          {tamperResult.agent_run.plan.map((p, i) => (
            <span key={i} className="chip" style={{ marginTop: 8 }}>{p.action} {shortUrn(p.resource)}</span>
          ))}
          {tamperResult.agent_run.results.length > 0 && (
            <table style={{ marginTop: 10 }}>
              <thead>
                <tr><th>action</th><th>resource</th><th>decision</th><th>policy / reason</th><th>audit</th></tr>
              </thead>
              <tbody>
                {tamperResult.agent_run.results.map((r, i) => (
                  <tr key={i}>
                    <td><span className="chip">{r.action}</span></td>
                    <td className="mono" style={{ fontSize: 11 }}>{shortUrn(r.resource)}</td>
                    <td><span className={`badge decision-${r.decision}`}>{cap(r.decision)}</span></td>
                    <td style={{ fontSize: 12 }}>{r.policy || r.reason}</td>
                    <td className="mono" style={{ fontSize: 11 }}>{r.audit_seq ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {chain && !chain.valid && (
        <div className="alert deny" style={{ marginTop: 12 }}>
          <strong>Integrity failure detected.</strong>
          {chain.issues.map((i, k) => (
            <div key={k} className="mono" style={{ marginTop: 4 }}>
              seq {i.seq} · {i.kind} · {i.detail}
            </div>
          ))}
          <IconButton icon="wrench" title="Repair chain" className="primary" onClick={repair} disabled={repairing} style={{ marginTop: 10 }} />
        </div>
      )}

      {error && <div className="alert deny" style={{ marginTop: 12 }}>{error}</div>}

      <div className="card filter-bar" style={{ marginTop: 16 }}>
        <input className="grow" placeholder="event_type" value={filters.event_type} onChange={(e) => setFilters({ ...filters, event_type: e.target.value })} />
        <input className="grow" placeholder="agent_id" value={filters.agent_id} onChange={(e) => setFilters({ ...filters, agent_id: e.target.value })} />
        <select value={filters.decision} onChange={(e) => setFilters({ ...filters, decision: e.target.value })}>
          <option value="">any decision</option>
          <option value="allow">allow</option>
          <option value="deny">deny</option>
        </select>
        <input type="number" placeholder="limit" value={filters.limit} onChange={(e) => setFilters({ ...filters, limit: Number(e.target.value) })} />
        <IconButton icon="refresh" title="Refresh" onClick={load} disabled={loading} />
      </div>

      {loading ? <Empty message="Loading…" /> : (
        <DataTable
          rows={events}
          rowKey={(e) => e.seq}
          initialSort="seq"
          columns={[
            { id: 'seq', header: 'seq', render: (e) => <span className="mono">{e.seq}</span>, sortValue: (e) => e.seq },
            { id: 'event_type', header: 'event_type', render: (e) => e.event_type },
            { id: 'actor_id', header: 'actor', render: (e) => <span className="mono">{e.actor_id}</span> },
            { id: 'subject', header: 'subject', render: (e) => <span className="mono">{e.subject}</span> },
            { id: 'decision', header: 'decision', render: (e) => <DecisionBadge decision={e.decision} />, sortValue: (e) => e.decision ?? '' },
            { id: 'hash', header: 'hash', render: (e) => <span className="mono">{short(e.event_hash)}</span> },
            { id: 'ts', header: 'ts', render: (e) => <span className="mono">{new Date(e.ts).toLocaleString()}</span>, sortValue: (e) => e.ts },
          ]}
          searchPlaceholder="Search payloads, actors, subjects…"
          expandRender={(e) => (
            <>
              <div className="mono-block">{JSON.stringify(e.payload, null, 2)}</div>
              <div className="mono-block" style={{ marginTop: 6 }}>prev: {e.prev_hash}</div>
              <div className="mono-block" style={{ marginTop: 6 }}>sig: {e.signed_by ?? 'unsigned'}</div>

              <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
                <IconButton
                  icon="file-text" size={14}
                  title={traces[e.seq] ? 'Reload impact trace' : 'Load impact trace'}
                  onClick={(ev) => {
                    ev.stopPropagation()
                    loadTrace(e.seq, e.id)
                  }}
                  disabled={traceLoading === e.seq}
                />
                {traces[e.seq]?.entity && (
                  <span className="chip">{traces[e.seq]?.entity?.name}</span>
                )}
                {traceError[e.seq] && (
                  <span style={{ color: 'var(--red)', fontSize: 12 }}>{traceError[e.seq]}</span>
                )}
              </div>

              {traces[e.seq] && <TracePanel trace={traces[e.seq]!} />}
            </>
          )}
        />
      )}
    </div>
  )
}

function TracePanel({ trace }: { trace: AuditTrace }) {
  const pd = trace.policy_decision
  const ent = trace.entity
  const facts = ent?.lineage_facts
  return (
    <div style={{ marginTop: 12, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
      <strong style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: 1, color: 'var(--muted)' }}>
        Impact trace — audit → decision → action → lineage → experiments
      </strong>

      <div className="grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)', marginTop: 10, gap: 10 }}>
        <div className="card" style={{ padding: 10 }}>
          <div className="label">Policy decision</div>
          {pd ? (
            <>
              <div>
                <DecisionBadge decision={pd.decision} /> <span className="mono" style={{ fontSize: 11 }}>{pd.engine}</span>
              </div>
              <div style={{ fontSize: 12, marginTop: 4 }}>
                <strong>{(pd.policy_input.action as { type?: string } | undefined)?.type || ''}</strong> on{' '}
                <span className="mono" style={{ fontSize: 11 }}>{shortUrn(String((pd.policy_input.action as { resource?: unknown } | undefined)?.resource || ''))}</span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>{pd.reason}</div>
            </>
          ) : (
            <div style={{ color: 'var(--muted)', fontSize: 12 }}>no decision row (identity/scope rejection)</div>
          )}
        </div>
        <div className="card" style={{ padding: 10 }}>
          <div className="label">Recorded action</div>
          {trace.action ? (
            <>
              <div><span className="chip">{trace.action.action_type}</span> <span className="mono" style={{ fontSize: 11 }}>weight {trace.action.impact_weight}</span></div>
              <div className="mono" style={{ fontSize: 11, marginTop: 4 }}>{trace.action.id}</div>
              {trace.action.audit && (
                <div style={{ fontSize: 11, marginTop: 4 }}>
                  audit <span className="mono">seq {trace.action.audit.seq}</span> · {trace.action.audit.event_id}
                </div>
              )}
            </>
          ) : (
            <div style={{ color: 'var(--muted)', fontSize: 12 }}>no DataHubAction (denied or non-catalog subject)</div>
          )}
        </div>
        <div className="card" style={{ padding: 10 }}>
          <div className="label">Entity</div>
          {ent ? (
            <>
              <div style={{ fontSize: 12 }}>{ent.name}</div>
              <div className="mono" style={{ fontSize: 11, marginTop: 4 }}>{shortUrn(ent.urn)}</div>
              <div style={{ fontSize: 11, marginTop: 4 }}>
                <span className="chip">{ent.data_classification}</span> <span className="chip">{ent.domain}</span>
              </div>
            </>
          ) : (
            <div style={{ color: 'var(--muted)', fontSize: 12 }}>not a catalog entity</div>
          )}
        </div>
        <div className="card" style={{ padding: 10 }}>
          <div className="label">Lineage facts</div>
          {facts ? (
            <div style={{ fontSize: 12 }}>
              <div><strong>{facts.downstream_count}</strong> downstream · <strong>{facts.upstream_restricted_count}</strong> restricted upstream</div>
              <div style={{ marginTop: 4 }}>criticality <strong>{facts.criticality.toFixed(2)}</strong> {facts.is_critical && <span className="chip">critical</span>}</div>
              <div style={{ marginTop: 4 }}>upstream restricted: <strong>{facts.upstream_restricted ? 'yes' : 'no'}</strong></div>
            </div>
          ) : (
            <div style={{ color: 'var(--muted)', fontSize: 12 }}>—</div>
          )}
        </div>
      </div>

      {pd && (
        <>
          <div className="label" style={{ marginTop: 12 }}>Policy input the engine evaluated</div>
          <div className="mono-block">{JSON.stringify(pd.policy_input, null, 2)}</div>
        </>
      )}

      <div className="label" style={{ marginTop: 12 }}>Impact analyses that covered this entity ({trace.experiments.length})</div>
      {trace.experiments.length === 0 ? (
        <div style={{ color: 'var(--muted)', fontSize: 12 }}>no experiments targeted this entity — run a what-if or custom experiment to link one</div>
      ) : (
        <table className="table" style={{ marginTop: 6 }}>
          <thead>
            <tr><th>id</th><th>name</th><th>kind</th><th>risk</th><th>root</th><th>created</th></tr>
          </thead>
          <tbody>
            {trace.experiments.map((x) => (
              <tr key={x.id}>
                <td className="mono" style={{ fontSize: 11 }}>{x.id}</td>
                <td style={{ fontSize: 12 }}>{x.name || '—'}</td>
                <td><span className="chip">{x.kind}</span></td>
                <td><span className={`badge ${x.risk === 'high' ? 'decision-deny' : x.risk === 'medium' ? 'decision-allow' : ''}`}>{cap(x.risk)}</span></td>
                <td className="mono" style={{ fontSize: 11 }}>{shortUrn(x.root_urn)}</td>
                <td className="mono" style={{ fontSize: 11 }}>{new Date(x.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
