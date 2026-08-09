import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { DataHubEntity, ImpactMatrix } from '../api/types'
import { ClassificationBadge, DataTable, Empty, IconButton, InfoTip, PageHeader } from '../components/ui'

const DOMAINS = ['General', 'Marketing', 'Sales', 'Finance', 'ML', 'Engineering', 'Healthcare', 'Order Entry']

export default function DataHub() {
  const [entities, setEntities] = useState<DataHubEntity[]>([])
  const [impact, setImpact] = useState<ImpactMatrix | null>(null)
  const [status, setStatus] = useState<{ connected: boolean; catalog_source: string; endpoint: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [domain, setDomain] = useState('')
  const [classification, setClassification] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [ents, imp, st] = await Promise.all([api.entities({ domain, classification }), api.impact(), api.datahubStatus()])
      setEntities(ents)
      setImpact(imp)
      setStatus(st)
    } catch (e) {
      setError(String((e as Error).message || e))
    } finally {
      setLoading(false)
    }
  }, [domain, classification])

  useEffect(() => { load() }, [load])

  const agents = impact ? Object.keys(impact.matrix) : []
  const maxWeight = impact
    ? Math.max(1, ...Object.values(impact.matrix).flatMap((row) => Object.values(row)))
    : 1

  return (
    <div>
      <PageHeader
        title="DataHub Catalog"
        subtitle="Governed datasets with domains, classifications, owners, lineage, and agent impact."
      />

      {status && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
          {status.connected ? (
            <span className="badge classification-public" title={`Connected to ${status.endpoint || 'DataHub'}`}>
              Live DataHub catalog
            </span>
          ) : (
            <span className="badge tier-standard" title="DATAHUB_ENDPOINT not set — showing the bundled reference catalog">
              Reference catalog mode
            </span>
          )}
        </div>
      )}

      {error && <div className="alert deny">{error}</div>}

      <div className="card grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        <div><div className="label">Entities</div><div className="value">{entities.length}</div></div>
        <div><div className="label">Domains</div><div className="value">{new Set(entities.map((e) => e.domain)).size}</div></div>
        <div><div className="label">Restricted</div><div className="value">{entities.filter((e) => e.data_classification === 'restricted').length}</div></div>
        <div><div className="label">Active agents</div><div className="value">{agents.length}</div></div>
      </div>

      {loading ? <Empty message="Loading…" /> : (
        <>
          <DataTable
            rows={entities}
            rowKey={(e) => e.urn}
            initialSort="name"
            searchPlaceholder="Search name, platform, domain, owner…"
            toolbar={
              <>
                <select className="dt-select" value={domain} onChange={(e) => setDomain(e.target.value)} title="Filter by domain">
                  <option value="">any domain</option>
                  {DOMAINS.map((d) => <option key={d} value={d}>{d}</option>)}
                </select>
                <select className="dt-select" value={classification} onChange={(e) => setClassification(e.target.value)} title="Filter by classification">
                  <option value="">any classification</option>
                  <option value="public">public</option>
                  <option value="sensitive">sensitive</option>
                  <option value="restricted">restricted</option>
                </select>
                <IconButton icon="refresh" title="Refresh" onClick={load} disabled={loading} />
              </>
            }
            columns={[
              {
                id: 'name',
                header: 'name',
                render: (e) => <Link className="mono" to={`/lineage?urn=${encodeURIComponent(e.urn)}`}>{e.name}</Link>,
                sortValue: (e) => e.name,
              },
              { id: 'platform', header: 'platform', render: (e) => e.platform, sortValue: (e) => e.platform },
              { id: 'domain', header: 'domain', render: (e) => e.domain, sortValue: (e) => e.domain },
              { id: 'classification', header: 'classification', render: (e) => <ClassificationBadge cls={e.data_classification} />, sortValue: (e) => e.data_classification },
              { id: 'owner_team', header: 'owner', render: (e) => e.owner_team, sortValue: (e) => e.owner_team },
              { id: 'lineage', header: 'lineage', render: (e) => <span className="mono">{e.upstream.length}↑ {e.downstream.length}↓</span>, sortValue: (e) => e.downstream.length },
            ]}
          />

          <h2 style={{ marginTop: 28, display: 'flex', alignItems: 'center', gap: 8 }}>
            Agent Impact Heatmap
            <InfoTip text="Weighted impact of actions per dataset — read 1.0, query 2.0, transform 3.0, write 4.0, ingest 2.5." />
          </h2>
          {impact && agents.length > 0 ? (
            <div className="card" style={{ marginTop: 8, overflowX: 'auto' }}>
              <table className="table heatmap">
                <thead>
                  <tr>
                    <th>agent</th>
                    {entities.slice(0, 10).map((e) => (
                      <th key={e.urn} title={e.urn}><Link className="mono" to={`/lineage?urn=${encodeURIComponent(e.urn)}`}>{e.name}</Link></th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {agents.map((a) => (
                    <tr key={a}>
                      <td className="mono">{a}</td>
                      {entities.slice(0, 10).map((e) => {
                        const v = impact.matrix[a]?.[e.urn] || 0
                        const c = impact.counts[a]?.[e.urn] || 0
                        const alpha = v / maxWeight
                        return (
                          <td key={e.urn} style={{ background: `rgba(120, 120, 255, ${alpha})`, textAlign: 'center' }}>
                            {c ? <span className="mono" style={{ color: alpha > 0.4 ? '#fff' : 'inherit' }}>{c}·{v.toFixed(1)}</span> : <span style={{ color: 'var(--muted)' }}>·</span>}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty message="No recorded agent impact yet." />}
        </>
      )}
    </div>
  )
}
