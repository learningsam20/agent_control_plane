import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { AgentKeyPair } from '../api/types'
import { IconButton, PageHeader } from '../components/ui'

const DOMAIN_OPTIONS = ['Marketing', 'Sales', 'Finance', 'Engineering', 'ML']

export default function RegisterAgent() {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [domains, setDomains] = useState<string[]>(['Marketing'])
  const [generating, setGenerating] = useState(false)
  const [result, setResult] = useState<AgentKeyPair | null>(null)
  const [error, setError] = useState('')

  const submit = async () => {
    setError('')
    setGenerating(true)
    try {
      const keys = await api.generateKeys()
      const reg = await api.registerAgent({
        name,
        description,
        public_key: keys.public_key,
        granted_domains: domains,
      })
      setResult(reg)
    } catch (e) {
      setError(String((e as Error).message || e))
    } finally {
      setGenerating(false)
    }
  }

  if (result) {
    return (
      <div>
        <PageHeader title="Agent onboarded" subtitle="Save the private key now — it is returned exactly once and never stored by the control plane." />
        <div className="card">
          <h3>Agent identity</h3>
          <table>
            <tbody>
              <tr><td style={{ width: 160 }}>agent id</td><td className="mono">{result.id}</td></tr>
              <tr><td>name</td><td>{result.name}</td></tr>
              <tr><td>public key</td><td className="mono-block">{result.public_key}</td></tr>
              <tr><td>private key</td><td className="mono-block">{result.private_key}</td></tr>
            </tbody>
          </table>
          <p style={{ color: 'var(--muted)', marginTop: 12 }}>
            The private key signs every request (non-repudiation). Store it securely, e.g.
            with the Python SDK: <span className="mono">AgentCredentials(...).save("agent.json")</span>
          </p>
          <IconButton icon="check" title="Done" className="primary" onClick={() => navigate('/agents')} />
        </div>
      </div>
    )
  }

  return (
    <div>
      <PageHeader title="Onboard an agent" subtitle="The control plane generates an Ed25519 keypair; the private key never leaves your hands." />
      <div className="card" style={{ maxWidth: 560 }}>
        <label className="field">
          <span>Agent name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. revenue-reporter" />
        </label>
        <label className="field">
          <span>Description</span>
          <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What this agent does" />
        </label>
        <label className="field">
          <span>Granted domains</span>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {DOMAIN_OPTIONS.map((d) => (
              <label key={d} style={{ display: 'flex', gap: 6, alignItems: 'center', background: 'var(--bg-3)', padding: '6px 10px', borderRadius: 8 }}>
                <input
                  type="checkbox"
                  checked={domains.includes(d)}
                  style={{ width: 'auto' }}
                  onChange={(e) => {
                    setDomains(e.target.checked ? [...domains, d] : domains.filter((x) => x !== d))
                  }}
                />
                {d}
              </label>
            ))}
          </div>
        </label>
        {error && <div className="alert deny">{error}</div>}
        <IconButton icon="key" title="Generate keys & register" className="primary" onClick={submit} disabled={generating || name.length < 2} />
      </div>
    </div>
  )
}
