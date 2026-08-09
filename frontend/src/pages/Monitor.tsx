import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type {
  CriticalityReport,
  CriticalityRow,
  ImpactMatrix,
  MonitorScan,
  WatchlistAlert,
  WatchlistEntry,
} from '../api/types'
import { ClassificationBadge, DataTable, Empty, IconButton, InfoTip, PageHeader, Stat, cap } from '../components/ui'

const RISK_COLORS: Record<string, string> = {
  public: '#6b7280',
  sensitive: '#f59e0b',
  restricted: '#ef4444',
}

function heatColor(weight: number, max: number): string {
  if (weight === 0) return 'var(--bg-2)'
  const t = weight / max
  const alpha = 0.2 + 0.8 * t
  const c = t > 0.66 ? 'var(--red)' : t > 0.33 ? 'var(--amber)' : 'var(--teal)'
  return `color-mix(in srgb, ${c} ${alpha * 100}%, var(--bg-2))`
}

function CriticalityBar({ row }: { row: CriticalityRow }) {
  const pct = Math.max(0, Math.min(100, row.criticality * 100))
  const color = pct >= 70 ? 'var(--red)' : pct >= 45 ? 'var(--amber)' : 'var(--teal)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 120 }}>
      <div style={{ flex: 1, height: 8, borderRadius: 4, background: 'var(--bg-3)' }}>
        <div style={{ width: `${pct}%`, height: 8, borderRadius: 4, background: color }} />
      </div>
      <span className="mono">{row.criticality.toFixed(2)}</span>
    </div>
  )
}

export default function Monitor() {
  const navigate = useNavigate()
  const [report, setReport] = useState<CriticalityReport | null>(null)
  const [matrix, setMatrix] = useState<ImpactMatrix | null>(null)
  const [watchlist, setWatchlist] = useState<WatchlistEntry[]>([])
  const [alerts, setAlerts] = useState<WatchlistAlert[]>([])
  const [scans, setScans] = useState<MonitorScan[]>([])
  const [scanning, setScanning] = useState(false)
  const [scanError, setScanError] = useState('')
  const [loggingBreaches, setLoggingBreaches] = useState(false)
  const [breachMsg, setBreachMsg] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [addUrn, setAddUrn] = useState('')
  const [threshold, setThreshold] = useState(0.5)
  const [topN, setTopN] = useState(15)

  const load = () => {
    setError('')
    Promise.all([
      api.criticality(),
      api.impact(),
      api.watchlist(),
      api.watchlistAlerts(),
      api.monitorScans(),
    ])
      .then(([r, m, w, a, s]) => {
        setReport(r)
        setMatrix(m)
        setWatchlist(w.entries)
        setAlerts(a.alerts)
        setScans(s)
      })
      .catch((e) => setError(String(e.message || e)))
  }

  useEffect(load, [])

  const runScan = async () => {
    setScanning(true)
    setScanError('')
    try {
      const scan = await api.runMonitorScan()
      setScans((prev) => [scan, ...prev.filter((s) => s.id !== scan.id)])
    } catch (e) {
      setScanError(String((e as Error)?.message || e))
    } finally {
      setScanning(false)
    }
  }

  const logBreaches = async () => {
    setLoggingBreaches(true)
    setBreachMsg('')
    try {
      const res = await api.recordWatchlistBreaches()
      setBreachMsg(res.recorded === 0
        ? 'No new breaches to record — all crossings already in the audit chain.'
        : `Recorded ${res.recorded} breach event(s) to the audit chain.`)
      load()
    } catch (e) {
      setBreachMsg(`Failed: ${String((e as Error)?.message || e)}`)
    } finally {
      setLoggingBreaches(false)
    }
  }

  const heatmap = useMemo(() => {
    if (!report || !matrix) return null
    const ents = report.entities.filter((r) => r.actions > 0 || r.downstream_count > 0)
      .slice(0, topN)
    const agents = Object.keys(matrix.matrix)
    let max = 1
    for (const urn of ents.map((e) => e.urn)) {
      for (const agent of agents) {
        max = Math.max(max, matrix.matrix[agent]?.[urn] || 0)
      }
    }
    return { ents, agents, max }
  }, [report, matrix, topN])

  const addEntry = async () => {
    if (!addUrn) return
    setBusy(true)
    try {
      await api.addWatchlist({ urn: addUrn, threshold })
      setAddUrn('')
      load()
    } catch (e) {
      setError(String((e as Error)?.message || e))
    } finally {
      setBusy(false)
    }
  }

  const removeEntry = async (id: number) => {
    await api.removeWatchlist(id)
    load()
  }

  if (error) return <div className="alert deny">{error}</div>
  if (!report || !heatmap) return <div className="alert info">Loading monitor…</div>

  const critical = report.summary.critical_entities

  return (
    <div>
      <PageHeader
        title="DataHub Monitor"
        subtitle="Criticality is computed from real lineage, recorded agent impact, classification and blast radius — then watched with per-entity thresholds."
      />

      <div className="grid cols-4">
        <Stat label="Catalog entities" value={report.count} sub={`${report.summary.top[0]?.name || '—'} leads`} />
        <Stat label="Critical entities" value={critical} sub="criticality ≥ 0.40" />
        <Stat label="Watchlist" value={watchlist.length} sub={alerts.length ? `${alerts.length} breached` : 'no breaches'} />
        <Stat label="Open alerts" value={alerts.length} sub="watchlist threshold crossings" />
      </div>

      {alerts.length > 0 && (
        <div className="card" style={{ marginTop: 16, borderColor: 'var(--red)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
              Active alerts
              <InfoTip text="Watchlisted entities whose current criticality has crossed their threshold. Log them to the audit chain as tamper-evident breach events." />
            </h3>
            <IconButton
              icon="activity" title="Log breaches to audit chain" className="danger"
              style={{ marginLeft: 'auto' }}
              onClick={logBreaches} disabled={loggingBreaches}
            />
          </div>
          {breachMsg && <div className="alert info" style={{ marginTop: 8 }}>{breachMsg}</div>}
          {alerts.map((a) => (
            <div key={a.watchlist_id} className="alert deny" style={{ marginTop: 8 }}>
              <b>{a.name}</b> ({a.domain}) criticality {a.current.toFixed(2)} exceeds watch threshold{' '}
              {a.threshold.toFixed(2)} by <b>+{a.delta.toFixed(2)}</b> — classification {a.classification}
            </div>
          ))}
        </div>
      )}

      <div className="card" style={{ marginTop: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
            Guardian monitor scan
            <InfoTip text="Runs the guardian agent through the same governed workflow as other agents: criticality, a policy-gap re-scan of every recorded action, and watchlist breaches — then persists a MonitorScan and audits it." />
          </h3>
          <span className="chip">ag_monitor · mona-guardian</span>
          <span className="chip">role: guardian</span>
          <IconButton
            icon="activity" title="Run governed scan" className="primary"
            style={{ marginLeft: 'auto' }}
            onClick={runScan} disabled={scanning}
          />
        </div>
        {scanError && <div className="alert deny" style={{ marginTop: 10 }}>{scanError}</div>}
        {scans.length > 0 && (
          <DataTable
            noMargin
            rows={scans}
            rowKey={(s) => s.id}
            pageSize={5}
            searchPlaceholder="Search scans…"
            searchText={(s) => `${s.id} ${s.risk} ${s.summary.run_id}`}
            expandRender={(s) => (
              <div>
                <div style={{ color: 'var(--muted)', fontSize: 12, marginBottom: 8 }}>
                  {s.summary.agent} · {s.summary.planner} · status {s.summary.status} · risk{' '}
                  <span className={`badge risk-${s.risk}`}>{cap(s.risk)}</span>
                </div>
                {s.findings.length === 0 && <div className="dt-empty">No findings in this scan.</div>}
                {s.findings.map((f, i) => (
                  <div key={i} className={`alert ${f.severity === 'high' ? 'deny' : 'info'}`} style={{ marginTop: 8 }}>
                    <b>{f.kind}</b> · {f.severity} — {f.detail}
                    {f.items && f.items.length > 0 && (
                      <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12 }}>
                        {f.items.slice(0, 8).map((it, j) => (
                          <li key={j} className="mono">
                            {String(it.name || it.agent || it.gap_id || '')}{' '}
                            {it.criticality ? `· ${Number(it.criticality).toFixed(2)}` : ''}
                            {it.delta ? `· +${Number(it.delta).toFixed(2)}` : ''}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            )}
            columns={[
              { id: 'id', header: 'scan', render: (s) => <span className="mono">{s.id}</span>, sortValue: (s) => s.id },
              { id: 'risk', header: 'risk', render: (s) => <span className={`badge risk-${s.risk}`}>{cap(s.risk)}</span>, sortValue: (s) => s.risk },
              { id: 'critical', header: 'critical', render: (s) => <span className="mono">{s.summary.critical_datasets}</span>, sortValue: (s) => s.summary.critical_datasets },
              { id: 'gaps', header: 'gaps', render: (s) => <span className="mono">{s.summary.policy_gaps}</span>, sortValue: (s) => s.summary.policy_gaps },
              { id: 'alerts', header: 'alerts', render: (s) => <span className="mono">{s.summary.watchlist_alerts}</span>, sortValue: (s) => s.summary.watchlist_alerts },
              { id: 'findings', header: 'findings', render: (s) => <span className="mono">{s.summary.findings}</span>, sortValue: (s) => s.summary.findings },
              { id: 'run', header: 'run id', render: (s) => <span className="mono" style={{ fontSize: 11 }}>{s.summary.run_id}</span>, sortValue: (s) => s.summary.run_id },
              { id: 'at', header: 'at', render: (s) => <span style={{ color: 'var(--muted)', fontSize: 12 }}>{new Date(s.created_at).toLocaleString()}</span>, sortValue: (s) => new Date(s.created_at).getTime() },
            ]}
            empty="No scans yet — run the guardian to get a posture snapshot."
          />
        )}
        {scans.length === 0 && !scanning && (
          <Empty message="No scans yet — run the guardian to get a posture snapshot." />
        )}
        {scanning && <div className="alert info" style={{ marginTop: 12 }}>Guardian scan in progress…</div>}
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <DataTable
          noMargin
          title="Criticality ranking"
          subtitle="0.35·centrality (PageRank) + 0.25·impact + 0.20·risk + 0.20·blast"
          rows={report.entities}
          rowKey={(r) => r.urn}
          initialSort="criticality"
          searchPlaceholder="Search entities…"
          searchText={(r) => `${r.name} ${r.type} ${r.domain} ${r.platform}`}
          onRowClick={(r) => navigate(`/lineage?urn=${encodeURIComponent(r.urn)}`)}
          columns={[
            { id: 'name', header: 'Entity', sortValue: (r) => r.name, render: (r) => (
              <div>
                <div style={{ fontWeight: 600 }}>{r.name}</div>
                <div className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>{r.type} · {r.platform}</div>
              </div>
            ) },
            { id: 'domain', header: 'Domain', sortValue: (r) => r.domain, render: (r) => r.domain },
            { id: 'class', header: 'Class', sortValue: (r) => r.data_classification, render: (r) => <ClassificationBadge cls={r.data_classification} /> },
            { id: 'downstream', header: 'Down', sortValue: (r) => r.downstream_count, render: (r) => <span className="mono">{r.downstream_count}</span> },
            { id: 'criticality', header: 'Score', sortValue: (r) => r.criticality, render: (r) => <CriticalityBar row={r} /> },
            { id: 'components', header: 'Components', sortValue: (r) => r.criticality, render: (r) => (
              <span className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>
                C {r.centrality.toFixed(2)} · I {r.impact.toFixed(2)} · R {r.risk.toFixed(2)} · B {r.blast.toFixed(2)}
              </span>
            ) },
          ]}
          empty="No entities scored yet."
        />

        <div className="card">
          <h3>Impacted-lineage heatmap</h3>
          <p style={{ color: 'var(--muted)', fontSize: 12, marginTop: 0 }}>
            Agent activity × entity — cell brightness is real recorded impact weight.
          </p>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
            <label style={{ fontSize: 12, color: 'var(--muted)' }}>
              top entities{' '}
              <select value={topN} onChange={(e) => setTopN(Number(e.target.value))}>
                {[10, 15, 20, 30].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className="heatmap">
              <thead>
                <tr>
                  <th style={{ textAlign: 'left', minWidth: 180 }}>entity</th>
                  {heatmap.agents.map((a) => (
                    <th key={a} title={a} style={{ textAlign: 'center' }}>{a.replace('ag_', '').slice(0, 8)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {heatmap.ents.map((e) => (
                  <tr
                    key={e.urn}
                    className="row-click"
                    onClick={() => navigate(`/lineage?urn=${encodeURIComponent(e.urn)}`)}
                    title="Open lineage for this entity"
                  >
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span
                          style={{
                            width: 8, height: 8, borderRadius: 2,
                            background: RISK_COLORS[e.data_classification] || '#6b7280',
                          }}
                        />
                        <span style={{ fontWeight: e.criticality >= 0.4 ? 700 : 400 }}>{e.name}</span>
                        <span className="mono" style={{ fontSize: 10, color: 'var(--muted)' }}>
                          {e.criticality.toFixed(2)}
                        </span>
                      </div>
                    </td>
                    {heatmap.agents.map((a) => {
                      const w = matrix!.matrix[a]?.[e.urn] || 0
                      return (
                        <td
                          key={a}
                          style={{ textAlign: 'center', background: heatColor(w, heatmap.max) }}
                          title={`${a} → ${e.name}: ${w}`}
                        >
                          <span style={{ fontSize: 10, color: w ? 'var(--text)' : 'transparent' }}>{w || '·'}</span>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Watchlist</h3>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
          <select
            value={addUrn}
            onChange={(e) => setAddUrn(e.target.value)}
            style={{ minWidth: 320 }}
          >
            <option value="">— add a watched entity —</option>
            {report.entities.map((e) => (
              <option key={e.urn} value={e.urn}>{e.name} · {e.domain}</option>
            ))}
          </select>
          <label style={{ fontSize: 12, color: 'var(--muted)' }}>
            alert at ≥{' '}
            <input
              type="number" min={0} max={1} step={0.05} value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              style={{ width: 72 }}
            />
          </label>
          <IconButton icon="plus" title="Add to watchlist" onClick={addEntry} disabled={!addUrn || busy} />
        </div>
        {watchlist.length === 0 ? (
          <Empty message="Nothing watched yet — add an entity to get threshold alerts." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Entity</th>
                <th>Domain</th>
                <th>Class</th>
                <th>Threshold</th>
                <th>Current</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {watchlist.map((w) => (
                <tr
                  key={w.id}
                  className="row-click"
                  onClick={() => navigate(`/lineage?urn=${encodeURIComponent(w.urn)}`)}
                  title="Open lineage for this entity"
                >
                  <td style={{ fontWeight: 600 }}>{w.name}</td>
                  <td>{w.domain}</td>
                  <td><ClassificationBadge cls={w.classification} /></td>
                  <td className="mono">{w.threshold.toFixed(2)}</td>
                  <td className="mono">{w.current.toFixed(2)}</td>
                  <td>
                    <span className={`badge ${w.breached ? 'decision-deny' : 'decision-allow'}`}>
                      {w.breached ? 'Breached' : 'Ok'}
                    </span>
                  </td>
                  <td>
                    <IconButton
                      icon="trash" size={14} title="Remove from watchlist" className="danger"
                      onClick={() => removeEntry(w.id)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
