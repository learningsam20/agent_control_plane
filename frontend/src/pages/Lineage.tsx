import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
  type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api } from '../api/client'
import type { DataHubEntity } from '../api/types'
import { ClassificationBadge, Empty, PageHeader } from '../components/ui'

function LineageNode({ data }: { data: { label: string; cls: string; focus: boolean; upstream: number; downstream: number } }) {
  return (
    <div className="dag-node" style={{
      border: `2px solid ${data.focus ? 'var(--accent)' : 'var(--bg-3)'}`,
      background: 'var(--bg-2)',
      borderRadius: 8,
      padding: '8px 12px',
      width: 180,
    }}>
      <div className="mono" style={{ fontWeight: data.focus ? 700 : 500, color: 'var(--text)', wordBreak: 'break-word', overflowWrap: 'anywhere' }}>{data.label}</div>
      <div style={{ marginTop: 4 }}><ClassificationBadge cls={data.cls} /></div>
      <div style={{ marginTop: 4, fontSize: 11, color: 'var(--muted)' }}>{data.upstream}↑ · {data.downstream}↓</div>
    </div>
  )
}

const nodeTypes: NodeTypes = { lineage: LineageNode }

export default function Lineage() {
  const [params, setParams] = useSearchParams()
  const urn = params.get('urn') || ''
  const [entities, setEntities] = useState<DataHubEntity[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    setError('')
    api.entities()
      .then((ents) => {
        setEntities(ents)
        if (!params.get('urn') && ents.length > 0) {
          setParams({ urn: ents[0].urn }, { replace: true })
        }
      })
      .catch((e) => setError(String((e as Error).message || e)))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const focus = useMemo(() => entities.find((e) => e.urn === urn), [entities, urn])
  const ancestors = useMemo(() => (focus ? focus.upstream : []), [focus])
  const descendants = useMemo(() => (focus ? focus.downstream : []), [focus])
  const included = useMemo(() => {
    if (!focus) return []
    return [focus, ...ancestors.map((u) => entities.find((e) => e.urn === u)).filter(Boolean) as DataHubEntity[],
      ...descendants.map((u) => entities.find((e) => e.urn === u)).filter(Boolean) as DataHubEntity[]]
  }, [focus, ancestors, descendants, entities])

  const byUrn = useMemo(() => new Map(included.map((e) => [e.urn, e])), [included])

  const { nodes, edges } = useMemo(() => {
    const ns: Node[] = included.map((e, i) => ({
      id: e.urn,
      type: 'lineage',
      position: { x: 60 + (i % 3) * 220, y: 60 + Math.floor(i / 3) * 130 },
      data: {
        label: e.name,
        cls: e.data_classification,
        focus: e.urn === urn,
        upstream: e.upstream.length,
        downstream: e.downstream.length,
      },
    }))
    const es: Edge[] = []
    for (const e of included) {
      for (const u of e.upstream) {
        if (byUrn.has(u)) {
          es.push({
            id: `${u}-${e.urn}`,
            source: u,
            target: e.urn,
            animated: e.urn === urn || u === urn,
            markerEnd: { type: MarkerType.ArrowClosed },
            style: { stroke: e.urn === urn || u === urn ? 'var(--accent)' : '#666' },
          })
        }
      }
    }
    return { nodes: ns, edges: es }
  }, [included, byUrn, urn])

  const selectEntity = useCallback((next: string) => {
    setParams({ urn: next })
  }, [setParams])

  return (
    <div>
      <PageHeader
        title="Data Lineage"
        subtitle={focus ? `Lineage graph for ${focus.name}` : 'Select a dataset to see its upstream sources and downstream consumers.'}
      />

      {error && <div className="alert deny">{error}</div>}
      {loading && <Empty message="Loading…" />}

      {!loading && (
        <div className="card" style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <label className="field" style={{ flex: '1 1 260px', marginBottom: 0 }}>
              <span>Entity</span>
              <select value={urn} onChange={(e) => selectEntity(e.target.value)}>
                {entities.map((e) => <option key={e.urn} value={e.urn}>{e.name}</option>)}
              </select>
            </label>
            {!focus && urn && (
              <div className="alert info" style={{ margin: 0, flex: '1 1 100%' }}>
                Entity not found in the catalog — pick one above or follow a lineage link.
              </div>
            )}
          </div>
        </div>
      )}

      {focus && (
        <div className="card" style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span className="chip">{focus.platform}</span>
              <span className="chip">{focus.domain}</span>
              <span className="chip">{focus.owner_team}</span>
            </div>
            <span className="mono" style={{ color: 'var(--muted)', fontSize: 11 }}>{focus.urn}</span>
          </div>
          {focus.description && <p style={{ color: 'var(--muted)', marginTop: 8 }}>{focus.description}</p>}
          <div style={{ marginTop: 8 }}>
            {ancestors.map((u) => (
              <button key={u} className="chip link-chip" onClick={() => selectEntity(u)}>
                ↑ {byUrn.get(u)?.name || u}
              </button>
            ))}
            {descendants.map((u) => (
              <button key={u} className="chip link-chip" onClick={() => selectEntity(u)}>
                ↓ {byUrn.get(u)?.name || u}
              </button>
            ))}
          </div>
        </div>
      )}

      <div style={{ height: 560, border: '1px solid var(--bg-3)', borderRadius: 12, overflow: 'hidden' }}>
        {nodes.length > 0 ? (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ maxZoom: 1 }}
            minZoom={0.3}
            nodesDraggable
            onNodeClick={(_, node) => selectEntity(node.id)}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="var(--border)" gap={24} />
            <Controls />
          </ReactFlow>
        ) : (
          <Empty message="No lineage data." />
        )}
      </div>
    </div>
  )
}
