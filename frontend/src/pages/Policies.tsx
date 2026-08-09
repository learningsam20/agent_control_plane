import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Policy, PolicyGap, PolicyGapPreview, PolicyGapReport } from '../api/types'
import { Empty, IconButton, PageHeader, SectionTitle, cap } from '../components/ui'

const EMPTY_FORM = {
  name: '',
  description: '',
  effect: 'deny' as 'allow' | 'deny',
  actions: '',
  conditions: '',
  order: 100,
}

function SevBadge({ severity }: { severity: string }) {
  return <span className={`badge sev-${severity}`}>{cap(severity)}</span>
}

function GapPreviewTable({ preview }: { preview: PolicyGapPreview }) {
  return (
    <div style={{ marginTop: 10 }}>
      <table>
        <thead>
          <tr><th>entity</th><th>before</th><th>after</th><th>governing policy</th></tr>
        </thead>
        <tbody>
          {preview.after.map((a, i) => (
            <tr key={a.entity}>
              <td className="mono">{a.entity}</td>
              <td><span className="badge decision-deny">{cap(preview.before[i]?.decision || 'deny')}</span></td>
              <td>
                <span className={`badge decision-${a.decision}`}>{cap(a.decision)}</span>
              </td>
              <td className="mono" style={{ color: 'var(--muted)', fontSize: 12 }}>{a.policy}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {preview.consistent
        ? <p className="alert allow" style={{ marginTop: 8 }}>Patch reinstates every affected action through the real policy engine (rule was not persisted).</p>
        : <p className="alert deny" style={{ marginTop: 8 }}>Patch does not fully reinstate access — review before applying.</p>}
    </div>
  )
}

export default function Policies() {
  const [policies, setPolicies] = useState<Policy[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [gaps, setGaps] = useState<PolicyGapReport | null>(null)
  const [gapLoading, setGapLoading] = useState(true)
  const [previews, setPreviews] = useState<Record<string, PolicyGapPreview>>({})
  const [applying, setApplying] = useState('')

  const loadGaps = useCallback(async () => {
    setGapLoading(true)
    try {
      setGaps(await api.policyGaps())
    } catch (e) {
      setError(String((e as Error).message || e))
    } finally {
      setGapLoading(false)
    }
  }, [])

  useEffect(() => { loadGaps() }, [loadGaps])

  const previewGap = async (gap: PolicyGap) => {
    setError('')
    try {
      const pv = await api.previewPolicyGap(gap.id)
      setPreviews((prev) => ({ ...prev, [gap.id]: pv }))
    } catch (e) {
      setError(String((e as Error).message || e))
    }
  }

  const applyGap = async (gap: PolicyGap) => {
    if (!window.confirm(`Apply patch ${gap.patch?.name}? The rule is persisted and audited.`)) return
    setApplying(gap.id)
    setError('')
    try {
      const created = await api.applyPolicyGap(gap.id)
      setPolicies((ps) => [...ps, created].sort((a, b) => a.order - b.order))
      await loadGaps()
    } catch (e) {
      setError(String((e as Error).message || e))
    } finally {
      setApplying('')
    }
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setPolicies(await api.listPolicies())
    } catch (e) {
      setError(String((e as Error).message || e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const toggle = async (p: Policy) => {
    setError('')
    try {
      const updated = await api.setPolicyEnabled(p.id, !p.enabled)
      setPolicies((ps) => ps.map((x) => (x.id === updated.id ? updated : x)))
    } catch (e) {
      setError(String((e as Error).message || e))
    }
  }

  const remove = async (p: Policy) => {
    if (!window.confirm(`Delete policy ${p.name}?`)) return
    setError('')
    try {
      await api.deletePolicy(p.id)
      setPolicies((ps) => ps.filter((x) => x.id !== p.id))
    } catch (e) {
      setError(String((e as Error).message || e))
    }
  }

  const submit = async () => {
    setError('')
    try {
      let conditions: unknown[] = []
      if (form.conditions.trim()) {
        conditions = JSON.parse(form.conditions)
      }
      const created = await api.createPolicy({
        name: form.name.trim(),
        description: form.description.trim(),
        effect: form.effect,
        actions: form.actions.split(',').map((a) => a.trim()).filter(Boolean),
        conditions,
        order: form.order,
        enabled: true,
      })
      setPolicies((ps) => [...ps, created].sort((a, b) => a.order - b.order))
      setForm(EMPTY_FORM)
      setShowForm(false)
    } catch (e) {
      setError(String((e as Error).message || e))
    }
  }

  return (
    <div>
      <PageHeader
        title="Policies"
        subtitle="Ordered, default-deny policy engine. First matching policy wins; enable, reorder, or create your own."
        actions={
          <IconButton icon={showForm ? 'x' : 'plus'} title={showForm ? 'Close form' : 'New policy'} className="primary"
            onClick={() => setShowForm(!showForm)} />
        }
      />

      {error && <div className="alert deny">{error}</div>}

      {showForm && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
            <label className="field">
              <span>Name</span>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="deny-demo-writes" />
            </label>
            <label className="field">
              <span>Effect</span>
              <select value={form.effect} onChange={(e) => setForm({ ...form, effect: e.target.value as 'allow' | 'deny' })}>
                <option value="deny">deny</option>
                <option value="allow">allow</option>
              </select>
            </label>
            <label className="field" style={{ gridColumn: '1 / -1' }}>
              <span>Description</span>
              <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </label>
            <label className="field">
              <span>Actions (comma-separated)</span>
              <input value={form.actions} onChange={(e) => setForm({ ...form, actions: e.target.value })} placeholder="read, query, transform" />
            </label>
            <label className="field">
              <span>Order (lowest evaluated first)</span>
              <input type="number" value={form.order} onChange={(e) => setForm({ ...form, order: Number(e.target.value) })} />
            </label>
            <label className="field" style={{ gridColumn: '1 / -1' }}>
              <span>Conditions (JSON array — leave empty for always-match)</span>
              <textarea rows={4} value={form.conditions} onChange={(e) => setForm({ ...form, conditions: e.target.value })}
                placeholder='[{"field": "resource.domain", "op": "in", "value": ["Marketing"]}]' className="mono" />
            </label>
          </div>
          <IconButton icon="plus" title="Create policy" className="primary" style={{ marginTop: 12 }} onClick={submit} />
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
          <SectionTitle hint="Recorded agent activity is re-evaluated through the real policy engine. When current policy would deny an action the agent demonstrably performs, a gap is reported with a targeted lab- patch you can preview and apply (audited).">
            Policy gap analysis
          </SectionTitle>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {gaps && gaps.count > 0 && <span className="badge decision-deny">{gaps.count} gap(s)</span>}
            <span className="mono" style={{ color: 'var(--muted)', fontSize: 12 }}>{gaps ? `${gaps.scanned_pairs} recorded action pairs scanned` : ''}</span>
          </div>
        </div>
        {gapLoading ? <Empty message="Scanning for gaps…" /> : gaps && gaps.count === 0 ? (
          <Empty message="No gaps — every recorded action is still permitted by current policy." />
        ) : (
          gaps?.gaps.map((gap) => (
            <div key={gap.id} className="card" style={{ marginTop: 8, borderColor: gap.severity === 'high' ? 'rgba(248,81,73,.5)' : 'var(--border)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                <div>
                  <SevBadge severity={gap.severity} />
                  <strong style={{ marginLeft: 8 }}>{gap.title}</strong>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  {gap.patch && (
                    <>
                      <IconButton icon="eye" size={14} title="Preview patch" onClick={() => previewGap(gap)} />
                      <IconButton icon="send" size={14} title="Apply patch" className="primary" onClick={() => applyGap(gap)} disabled={applying === gap.id} />
                    </>
                  )}
                </div>
              </div>
              <p style={{ color: 'var(--muted)', margin: '8px 0 0', fontSize: 13 }}>{gap.detail}</p>
              <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {gap.denied.map((d) => (
                  <span key={d.urn} className="chip" title={`${d.policy_name}`}>
                    {d.name} · {d.domain} · {d.classification}
                  </span>
                ))}
              </div>
              {gap.patch && (
                <div className="mono-block" style={{ marginTop: 8 }}>
                  <div style={{ color: 'var(--muted)' }}>{gap.patch.summary}</div>
                  <div style={{ marginTop: 4, fontSize: 12 }}>
                    {gap.patch.name} · {gap.patch.effect} [{gap.patch.actions.join(', ')}] · order {gap.patch.order}
                  </div>
                </div>
              )}
              {previews[gap.id] && <GapPreviewTable preview={previews[gap.id]} />}
            </div>
          ))
        )}
      </div>

      {showForm && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
            <label className="field">
              <span>Name</span>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="deny-demo-writes" />
            </label>
            <label className="field">
              <span>Effect</span>
              <select value={form.effect} onChange={(e) => setForm({ ...form, effect: e.target.value as 'allow' | 'deny' })}>
                <option value="deny">deny</option>
                <option value="allow">allow</option>
              </select>
            </label>
            <label className="field" style={{ gridColumn: '1 / -1' }}>
              <span>Description</span>
              <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </label>
            <label className="field">
              <span>Actions (comma-separated)</span>
              <input value={form.actions} onChange={(e) => setForm({ ...form, actions: e.target.value })} placeholder="read, query, transform" />
            </label>
            <label className="field">
              <span>Order (lowest evaluated first)</span>
              <input type="number" value={form.order} onChange={(e) => setForm({ ...form, order: Number(e.target.value) })} />
            </label>
            <label className="field" style={{ gridColumn: '1 / -1' }}>
              <span>Conditions (JSON array — leave empty for always-match)</span>
              <textarea rows={4} value={form.conditions} onChange={(e) => setForm({ ...form, conditions: e.target.value })}
                placeholder='[{"field": "resource.domain", "op": "in", "value": ["Marketing"]}]' className="mono" />
            </label>
          </div>
          <IconButton icon="plus" title="Create policy" className="primary" style={{ marginTop: 12 }} onClick={submit} />
        </div>
      )}

      {loading ? <Empty message="Loading…" /> : (
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ padding: '14px 16px 0' }}>
            <SectionTitle hint="Ordered rules evaluated on every gateway decision. First match wins; disable a policy to stop enforcing it without deleting it.">
              Policies & enforcement status
            </SectionTitle>
          </div>
          <div>
          {policies.map((p) => (
            <div className="card" key={p.id} style={{ borderLeft: '0', borderRight: '0', borderTop: '0', borderRadius: 0, boxShadow: 'none' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <span className="chip">#{p.order}</span>
                  <strong style={{ marginLeft: 8 }}>{p.name}</strong>
                  <span className={`badge decision-${p.effect}`} style={{ marginLeft: 8, textTransform: 'uppercase' }}>{p.effect}</span>
                  {p.enabled ? <span className="badge status-active">enabled</span> : <span className="badge status-suspended">disabled</span>}
                  <span className="chip" style={{ marginLeft: 8 }}>{p.id}</span>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <IconButton icon={p.enabled ? 'pause' : 'activate'} size={14} title={p.enabled ? 'Disable' : 'Enable'} onClick={() => toggle(p)} />
                  <IconButton icon="trash" size={14} title="Delete" className="danger" onClick={() => remove(p)} />
                </div>
              </div>
              {p.description && <p style={{ color: 'var(--muted)', margin: '8px 0 0' }}>{p.description}</p>}
              <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {p.actions.map((a) => <span className="chip" key={a}>{a}</span>)}
                {p.conditions.length > 0 && <div className="mono-block" style={{ width: '100%', marginTop: 6 }}>{JSON.stringify(p.conditions, null, 2)}</div>}
              </div>
            </div>
          ))}
          </div>
        </div>
      )}
    </div>
  )
}
