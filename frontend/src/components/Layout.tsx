import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

const NAV = [
  { to: '/', label: 'Dashboard', icon: '▦' },
  { to: '/agents', label: 'Agents', icon: '◉' },
  { to: '/delegations', label: 'Delegations', icon: '⇄' },
  { to: '/zero-trust', label: 'Zero-Trust Lab', icon: '⛨' },
  { to: '/runs', label: 'Agent Runs', icon: '▶' },
  { to: '/audit', label: 'Audit Trail', icon: '≡' },
  { to: '/policies', label: 'Policies', icon: '⚖' },
  { to: '/datahub', label: 'DataHub', icon: '◆' },
  { to: '/lineage', label: 'Lineage', icon: '⌬' },
  { to: '/monitor', label: 'Monitor', icon: '✚' },
  { to: '/impact', label: 'Impact', icon: '☈' },
  { to: '/help', label: 'Help', icon: '?' },
]

const THEME_KEY = 'acp-theme'
const COLLAPSE_KEY = 'acp-sidebar-collapsed'

export default function Layout() {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    const stored = localStorage.getItem(THEME_KEY)
    return stored === 'light' ? 'light' : 'dark'
  })
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === '1')

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem(THEME_KEY, theme)
  }, [theme])

  useEffect(() => {
    localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0')
  }, [collapsed])

  return (
    <div className={`layout${collapsed ? ' layout-collapsed' : ''}`}>
      <aside className={`sidebar${collapsed ? ' collapsed' : ''}`}>
        <div className="brand">
          <div className="brand-mark">ACP</div>
          {!collapsed && (
            <div>
              <div className="brand-title">Agent Control Plane</div>
            </div>
          )}
          <button
            type="button"
            className="collapse-toggle"
            onClick={() => setCollapsed((c) => !c)}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? '»' : '«'}
          </button>
        </div>
        <nav>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
              title={collapsed ? item.label : undefined}
            >
              <span className="nav-icon">{item.icon}</span>
              {!collapsed && item.label}
            </NavLink>
          ))}
        </nav>
        <button
          type="button"
          className="theme-toggle"
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          <span className="theme-icon">{theme === 'dark' ? '☀' : '☾'}</span>
          {!collapsed && (theme === 'dark' ? 'Light mode' : 'Dark mode')}
        </button>
        {!collapsed && (
          <div className="sidebar-foot">
            Powered by Datahub
          </div>
        )}
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
