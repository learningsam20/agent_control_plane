import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Agents from './pages/Agents'
import RegisterAgent from './pages/RegisterAgent'
import AgentDetail from './pages/AgentDetail'
import Delegations from './pages/Delegations'
import ZeroTrustLab from './pages/ZeroTrustLab'
import AgentRuns from './pages/AgentRuns'
import AuditTrail from './pages/AuditTrail'
import Policies from './pages/Policies'
import DataHub from './pages/DataHub'
import Monitor from './pages/Monitor'
import Help from './pages/Help'

const Lineage = lazy(() => import('./pages/Lineage'))
const ImpactAnalysis = lazy(() => import('./pages/ImpactAnalysis'))

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/agents" element={<Agents />} />
        <Route path="/agents/register" element={<RegisterAgent />} />
        <Route path="/agents/:id" element={<AgentDetail />} />
        <Route path="/delegations" element={<Delegations />} />
        <Route path="/zero-trust" element={<ZeroTrustLab />} />
        <Route path="/runs" element={<AgentRuns />} />
        <Route path="/audit" element={<AuditTrail />} />
        <Route path="/policies" element={<Policies />} />
        <Route path="/datahub" element={<DataHub />} />
        <Route path="/monitor" element={<Monitor />} />
        <Route path="/lineage" element={
          <Suspense fallback={<div className="card">Loading lineage…</div>}>
            <Lineage />
          </Suspense>
        } />
        <Route path="/impact" element={
          <Suspense fallback={<div className="card">Loading impact analysis…</div>}>
            <ImpactAnalysis />
          </Suspense>
        } />
        <Route path="/help" element={<Help />} />
      </Route>
    </Routes>
  )
}
