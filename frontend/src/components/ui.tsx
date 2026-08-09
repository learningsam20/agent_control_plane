import { Fragment, useMemo, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'

export function cap(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s
}

const ICONS: Record<string, ReactNode> = {
  info: (<><circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" /></>),
  play: (<path d="M6 4l14 8-14 8z" fill="currentColor" stroke="none" />),
  plus: (<><path d="M12 5v14" /><path d="M5 12h14" /></>),
  zap: (<polygon points="13 2 3 14 12 14 11 22 21 10 12 10" />),
  trash: (<><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /><path d="M10 11v6" /><path d="M14 11v6" /></>),
  eye: (<><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></>),
  search: (<><circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" /></>),
  refresh: (<><polyline points="23 4 23 10 17 10" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" /></>),
  download: (<><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><path d="M12 15V3" /></>),
  wrench: (<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />),
  x: (<><path d="M18 6L6 18" /><path d="M6 6l12 12" /></>),
  check: (<polyline points="20 6 9 17 4 12" />),
  ban: (<><circle cx="12" cy="12" r="10" /><path d="M4.93 4.93l14.14 14.14" /></>),
  pause: (<><rect x="6" y="4" width="4" height="16" rx="1" /><rect x="14" y="4" width="4" height="16" rx="1" /></>),
  activate: (<><circle cx="12" cy="12" r="10" /><path d="M10 8l6 4-6 4z" fill="currentColor" stroke="none" /></>),
  reset: (<><polyline points="1 4 1 10 7 10" /><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" /></>),
  key: (<path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />),
  activity: (<polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />),
  'file-text': (<><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><path d="M16 13H8" /><path d="M16 17H8" /><path d="M10 9H8" /></>),
  send: (<><path d="M22 2L11 13" /><polygon points="22 2 15 22 11 13 2 9" /></>),
  save: (<><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" /><polyline points="17 21 17 13 7 13 7 21" /><polyline points="7 3 7 8 15 8" /></>),
  shield: (<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />),
}

export type IconName = keyof typeof ICONS

export function Icon({ name, size = 15 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {ICONS[name]}
    </svg>
  )
}

export function IconButton({
  icon,
  title,
  onClick,
  disabled,
  className = '',
  style,
  size,
}: {
  icon: IconName
  title: string
  onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void
  disabled?: boolean
  className?: string
  style?: React.CSSProperties
  size?: number
}) {
  return (
    <button
      type="button"
      className={`icon-btn ${className}`}
      title={title}
      aria-label={title}
      onClick={onClick}
      disabled={disabled}
      style={style}
    >
      <Icon name={icon} size={size} />
    </button>
  )
}

export function InfoTip({ text }: { text: string }) {
  const anchorRef = useRef<HTMLSpanElement>(null)
  const bubbleRef = useRef<HTMLSpanElement>(null)
  const [style, setStyle] = useState<CSSProperties | null>(null)

  const show = () => {
    const anchor = anchorRef.current
    const bubble = bubbleRef.current
    if (!anchor || !bubble) return
    const r = anchor.getBoundingClientRect()
    const bw = bubble.offsetWidth
    const bh = bubble.offsetHeight
    const pad = 10
    const left = Math.max(pad, Math.min(window.innerWidth - bw - pad, r.left + r.width / 2 - bw / 2))
    const above = r.top - bh - pad
    const top = above < pad ? r.bottom + pad : above
    setStyle({ position: 'fixed', top, left, opacity: 1, visibility: 'visible' })
  }

  const hide = () => setStyle(null)

  return (
    <span
      ref={anchorRef}
      className="info-tip"
      aria-label={text}
      role="note"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      <Icon name="info" size={14} />
      <span ref={bubbleRef} className="info-tip-bubble" style={style ?? undefined}>{text}</span>
    </span>
  )
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: string }) {
  return (
    <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      {children}
      {hint ? <InfoTip text={hint} /> : null}
    </h3>
  )
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub ? <div className="sub">{sub}</div> : null}
    </div>
  )
}

export function TierBadge({ tier }: { tier: string }) {
  return <span className={`badge tier-${tier}`}>{cap(tier)}</span>
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge status-${status}`}>{cap(status)}</span>
}

export function DecisionBadge({ decision }: { decision: string | null }) {
  if (!decision) return <span className="badge">—</span>
  return <span className={`badge decision-${decision}`}>{cap(decision)}</span>
}

export function ClassificationBadge({ cls }: { cls: string }) {
  return <span className={`badge classification-${cls}`}>{cap(cls)}</span>
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
        <div>
          <h1>{title}</h1>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
        {actions ? <div className="page-head-actions">{actions}</div> : null}
      </div>
    </div>
  )
}

export function ScoreBar({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, score))
  const color = pct >= 80 ? 'var(--purple)' : pct >= 60 ? 'var(--accent)' : pct >= 40 ? 'var(--teal)' : 'var(--red)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div style={{ flex: 1, height: 8, borderRadius: 4, background: 'var(--bg-3)' }}>
        <div style={{ width: `${pct}%`, height: 8, borderRadius: 4, background: color }} />
      </div>
      <span className="mono">{score.toFixed(1)}</span>
    </div>
  )
}

export function Empty({ message }: { message: string }) {
  return <div className="card" style={{ color: 'var(--muted)', textAlign: 'center' }}>{message}</div>
}

export type SortDir = 'asc' | 'desc'

export interface DataColumn<T> {
  id: string
  header: ReactNode
  render: (row: T) => ReactNode
  sortValue?: (row: T) => string | number
  className?: string
}

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  pageSize = 10,
  pageSizeOptions = [10, 25, 50, 100],
  searchable = true,
  searchPlaceholder = 'Search…',
  searchText,
  empty = 'No rows to show.',
  initialSort,
  initialDir = 'desc',
  onRowClick,
  expandRender,
  footer,
  title,
  subtitle,
  noMargin,
  toolbar,
}: {
  rows: T[]
  columns: DataColumn<T>[]
  rowKey: (row: T) => string | number
  pageSize?: number
  pageSizeOptions?: number[]
  searchable?: boolean
  searchPlaceholder?: string
  searchText?: (row: T) => string
  empty?: ReactNode
  initialSort?: string
  initialDir?: SortDir
  onRowClick?: (row: T) => void
  expandRender?: (row: T) => ReactNode
  footer?: ReactNode
  title?: ReactNode
  subtitle?: ReactNode
  noMargin?: boolean
  toolbar?: ReactNode
}) {
  const [query, setQuery] = useState('')
  const [sortId, setSortId] = useState<string | undefined>(initialSort)
  const [dir, setDir] = useState<SortDir>(initialDir)
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(pageSize)
  const [expanded, setExpanded] = useState<string | number | null>(null)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return rows
    return rows.filter((r) => {
      const text = searchText ? searchText(r) : JSON.stringify(r)
      return text.toLowerCase().includes(q)
    })
  }, [rows, query, searchText])

  const sorted = useMemo(() => {
    const col = columns.find((c) => c.id === sortId)
    if (!col) return filtered
    const sv = col.sortValue ?? ((r: T) => String((r as Record<string, unknown>)[col.id] ?? ''))
    const arr = [...filtered]
    arr.sort((a, b) => {
      const av = sv(a)
      const bv = sv(b)
      const cmp = typeof av === 'number' && typeof bv === 'number' ? av - bv : String(av).localeCompare(String(bv))
      return dir === 'asc' ? cmp : -cmp
    })
    return arr
  }, [filtered, columns, sortId, dir])

  const totalPages = Math.max(1, Math.ceil(sorted.length / size))
  const cur = Math.min(page, totalPages)
  const pageRows = sorted.slice((cur - 1) * size, cur * size)
  const start = sorted.length === 0 ? 0 : (cur - 1) * size + 1
  const end = Math.min(sorted.length, cur * size)

  const toggleSort = (id: string) => {
    if (sortId === id) setDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else {
      setSortId(id)
      setDir('desc')
    }
    setPage(1)
  }

  const pages = Array.from({ length: totalPages }, (_, i) => i + 1)

  return (
    <div className="card dt-wrap" style={{ marginTop: noMargin ? 0 : 12 }}>
      {(title || subtitle) && (
        <div className="dt-head">
          {title && <h3 style={{ margin: 0 }}>{title}</h3>}
          {subtitle && <p style={{ color: 'var(--muted)', fontSize: 12, margin: '4px 0 0' }}>{subtitle}</p>}
        </div>
      )}
      <div className="dt-toolbar">
        {searchable ? (
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setPage(1)
            }}
            placeholder={searchPlaceholder}
          />
        ) : (
          <div />
        )}
        {toolbar}
        <span className="dt-count">{sorted.length} row{sorted.length === 1 ? '' : 's'}</span>
        <select className="dt-select" value={size} onChange={(e) => { setSize(Number(e.target.value)); setPage(1) }}>
          {pageSizeOptions.map((n) => (
            <option key={n} value={n}>{n} / page</option>
          ))}
        </select>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table className="table" style={{ margin: 0 }}>
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.id} className="dt-sort" onClick={() => toggleSort(c.id)}>
                  {c.header}
                  {sortId === c.id ? <span className="arrow">{dir === 'asc' ? ' ↑' : ' ↓'}</span> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((r) => {
              const k = rowKey(r)
              const isOpen = Boolean(expandRender && expanded === k)
              return (
                <Fragment key={k}>
                  <tr
                    className={onRowClick || expandRender ? 'row-click' : undefined}
                    onClick={() => {
                      if (expandRender) setExpanded(isOpen ? null : k)
                      onRowClick?.(r)
                    }}
                  >
                    {columns.map((c) => (
                      <td key={c.id} className={c.className}>{c.render(r)}</td>
                    ))}
                  </tr>
                  {isOpen && (
                    <tr>
                      <td colSpan={columns.length} className="dt-expanded">{expandRender!(r)}</td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
        {sorted.length === 0 && <div className="dt-empty">{empty}</div>}
      </div>

      {footer}

      {totalPages > 1 && (
        <div className="dt-pager">
          <button className="secondary" disabled={cur <= 1} onClick={() => setPage(cur - 1)}>‹ Previous</button>
          {pages.map((p) => (
            <button
              key={p}
              className={`secondary dt-page-btn${p === cur ? ' active' : ''}`}
              onClick={() => setPage(p)}
            >
              {p}
            </button>
          ))}
          <button className="secondary" disabled={cur >= totalPages} onClick={() => setPage(cur + 1)}>Next ›</button>
          <span className="dt-count">{start}–{end} of {sorted.length}</span>
        </div>
      )}
    </div>
  )
}
