import { useState } from 'react'
import type { ReactNode } from 'react'
import { Empty, PageHeader } from '../components/ui'

const PERSONAS: Array<{
  name: string
  goal: string
  pages: Array<[string, string]>
  flow: string[]
  tips: string[]
}> = [
  {
    name: 'Data analyst',
    goal: 'Find governed datasets, read and query them through a governed agent, and prove the activity on the audit chain.',
    pages: [
      ['DataHub', 'Browse the catalog and filter by domain and classification to find the right dataset.'],
      ['Lineage', 'Trace upstream sources and downstream consumers before relying on a dataset.'],
      ['Agent Runs', 'Run a read/query objective through a governed agent and see each decision.'],
      ['Audit Trail', 'Confirm your requests and every decision landed on the tamper-evident chain.'],
    ],
    flow: [
      'Start in DataHub, filter by domain/classification, and pick the dataset you need.',
      'Run a read or query objective in Agent Runs and watch how the gateway decides.',
      'If restricted data is denied, ask a privileged owner for a scoped delegation (see Delegations).',
    ],
    tips: [
      'Default-deny means restricted data stays blocked until a delegation grants exactly that scope.',
      'Use Impact → What-if before trusting a dataset that may be changing.',
    ],
  },
  {
    name: 'Data engineer',
    goal: 'Build and run pipelines, transform and refine data, and grant colleagues the least access they need.',
    pages: [
      ['Delegations', 'Issue scoped, time-limited grants of actions + datasets to lower-tier agents.'],
      ['Policies', 'Create deny-first guardrails and explicit allow rules for your pipelines.'],
      ['Agent Runs', 'Run governed pipeline objectives and watch the planner execute them.'],
      ['Impact', 'Simulate schema changes or outages before they reach production.'],
    ],
    flow: [
      'Delegate read/query on a restricted mart to an analyst with the exact datasets and a TTL.',
      'When a contract changes, run Impact → What-if (schema drift, new upstream) to see the blast radius.',
      'Run the pipeline as an Agent Run and verify the steps on the audit chain.',
    ],
    tips: [
      'Delegations are enforced by the gateway: anything outside the granted scope is denied.',
      'Revoke a delegation as soon as the need passes — it is one click on Delegations.',
    ],
  },
  {
    name: 'ML engineer',
    goal: 'Train models on feature stores and deploy predictions, without leaking restricted features.',
    pages: [
      ['DataHub', 'Locate feature stores and see which agents already touch them.'],
      ['Impact', 'Run what-if on feature changes (new upstream, staleness) before retraining.'],
      ['Agent Runs', 'Run governed training/deploy objectives and observe allow/deny decisions.'],
      ['Monitor', 'Watch criticality and watchlist alerts on the models you depend on.'],
    ],
    flow: [
      'Check the feature store in DataHub and confirm classifications allow your use case.',
      'Run what-if experiments to see the blast radius of a feature change.',
      'Deploy through a governed Agent Run and audit each step.',
    ],
    tips: [
      'Restricted features require a scoped delegation or an explicit allow policy — check Policy gaps if denied.',
      'The impact heatmap shows which agents already act on the datasets you plan to use.',
    ],
  },
  {
    name: 'Security guardian',
    goal: 'Monitor control-plane posture, find policy gaps, and prove compliance with tamper-evident audit.',
    pages: [
      ['Monitor', 'Review criticality, run governed scans, and manage the watchlist and active alerts.'],
      ['Audit Trail', 'Verify chain integrity, simulate tampering to test detection, and export evidence.'],
      ['Policies', 'Run gap analysis to find activity your policies would deny and apply targeted patches.'],
      ['Zero-Trust Lab', 'Validate a scenario end-to-end before anything is enforced.'],
    ],
    flow: [
      'Start on the Dashboard for a posture snapshot: chain validity, decisions, tiers.',
      'Run a governed scan on Monitor and review criticality, gaps, and watchlist findings.',
      'Verify the chain on Audit Trail and export CSV/JSON for external evidence.',
    ],
    tips: [
      'Repair recomputes the chain after a tamper test and strips the markers — run it to restore VALID.',
      'Policy-gap patches are proposed only after being previewed — apply them to close real gaps.',
    ],
  },
  {
    name: 'Platform administrator',
    goal: 'Run the control plane: onboard and control agents, own policies, and keep the chain healthy.',
    pages: [
      ['Agents', 'Register agents (Ed25519 keypair), suspend/revoke/activate, inspect reputation.'],
      ['Policies', 'Own the rulebook: enable/disable, delete, and close gaps.'],
      ['Delegations', 'Oversee all active grants and revoke them from one place.'],
      ['Dashboard', 'Monitor headline stats: agents, delegations, decisions, chain validity.'],
    ],
    flow: [
      'Onboard a new agent via Agents → Register and hand over the generated keypair.',
      'Suspend or revoke immediately when an agent misbehaves — the guardrail blocks them.',
      'Review the chain badge on the Dashboard; investigate via Audit Trail if it ever reads TAMPERED.',
    ],
    tips: [
      'Revoke is permanent — re-register the agent if you need it back.',
      'The Zero-Trust Lab reset clears lab-generated policies and restores demo agents.',
    ],
  },
]

const FAQS: Array<{ q: string; a: string }> = [
  {
    q: 'Why was my request denied?',
    a: 'Every request is evaluated by the gateway: default-deny guardrails run first (inactive agents, delegation depth, out-of-domain access), then permissive allow policies. The deny reason is shown on the request and recorded on the audit chain — open the trace to see exactly which policy or guardrail rejected it.',
  },
  {
    q: 'How do I grant an agent access to a restricted dataset?',
    a: 'Issue a scoped delegation from a privileged agent on the Delegations page: choose the delegatee, the actions (e.g. read, query) and the exact datasets. The gateway only allows those actions on those datasets and rejects anything outside the scope.',
  },
  {
    q: 'What does TAMPERED mean on the audit chain?',
    a: 'The block hash chain did not recompute cleanly — a block was altered after it was written. Use Simulate tamper on the Audit Trail page to demonstrate detection, then Repair to recompute the chain and restore VALID status.',
  },
  {
    q: 'How do I cut an agent off immediately?',
    a: 'Agents → Suspend (reversible) or Revoke (permanent). Suspended or revoked agents are blocked by the first guardrail policy, so they can never act again until reactivated.',
  },
  {
    q: 'Can a delegation be used beyond its scope?',
    a: 'No. The token is checked on every call: the agent may only perform the granted actions on the granted datasets, within the validity window and depth limit. Expired or revoked tokens are rejected by the gateway.',
  },
  {
    q: 'What happens when I approve a scenario in the Zero-Trust Lab?',
    a: 'The generated policies are persisted and enabled, the scoped delegation is issued, and every step is re-run through the real signed gateway and appended to the audit chain. Preview the simulation before approving to confirm the decisions match your intent.',
  },
  {
    q: 'Do what-if experiments change real data?',
    a: 'No. What-if and custom experiments simulate against the lineage graph in memory. The result is persisted as an experiment and audited, but nothing about your actual data, policies or agents changes.',
  },
  {
    q: 'What is a policy gap?',
    a: 'A policy gap is recorded activity that your current policies would deny. The gap analysis on the Policies page re-evaluates recorded activity and proposes a targeted patch — preview it, then apply it to close the gap.',
  },
  {
    q: 'How do I onboard a new agent?',
    a: 'Agents → Register. The platform generates an Ed25519 keypair the agent uses to sign every gateway request. New agents start untrusted and rise with reputation.',
  },
]

const PAGES: Array<{ page: string; icon: string; when: string; how: string }> = [
  { page: 'Dashboard', icon: '▦', when: 'Get a posture snapshot at a glance', how: 'Read the headline stats, tier/decision charts, and the audit chain badge; watch recent events.' },
  { page: 'Agents', icon: '◉', when: 'Register, inspect, or control an agent', how: 'Register to get a keypair; Suspend/Revoke to cut access instantly; reactivate to restore.' },
  { page: 'Delegations', icon: '⇄', when: 'Grant scoped, time-limited access', how: 'Pick a privileged delegator, the delegatee, actions + datasets, and a TTL. Revoke when done.' },
  { page: 'Zero-Trust Lab', icon: '⛨', when: 'Validate a scenario before enforcing it', how: 'Define → transform → preview → approve. Nothing is persisted until you approve.' },
  { page: 'Agent Runs', icon: '▶', when: 'Let a governed agent act on an objective', how: 'Set an objective, run it, and inspect each per-step decision on the audit trail.' },
  { page: 'Audit Trail', icon: '≡', when: 'Prove or inspect what happened', how: 'Verify the chain; simulate tamper then repair to see detection; export CSV/JSON; open traces.' },
  { page: 'Policies', icon: '⚖', when: 'Define what is allowed and find gaps', how: 'Create deny-first guardrails and explicit allows; run gap analysis and apply a patch.' },
  { page: 'DataHub', icon: '◆', when: 'Find datasets and see who touches them', how: 'Browse/filter the catalog by domain and classification; use the heatmap for agent intensity.' },
  { page: 'Lineage', icon: '⌬', when: 'Trace producers and consumers of a dataset', how: 'Select an entity to see upstream sources and downstream consumers with classifications.' },
  { page: 'Monitor', icon: '✚', when: 'Track criticality and watch for risk', how: 'Add watchlist entries with thresholds; review active alerts; run a governed scan.' },
  { page: 'Impact', icon: '☈', when: 'Simulate the blast radius of a change', how: 'Run a what-if (outage, classification change, schema drift…) or chain steps in the custom builder.' },
]

const RECIPES: Array<{ title: string; steps: string[] }> = [
  {
    title: 'Let an analyst read restricted data safely',
    steps: [
      'Agents → confirm the analyst agent is active.',
      'Delegations → issue a scoped grant: actions = read, query · datasets = the billing mart.',
      'Agent Runs → run a read objective and verify it is allowed.',
      'Audit Trail → confirm the grant and each read are on the chain.',
    ],
  },
  {
    title: 'Prove an audit chain was not altered',
    steps: [
      'Audit Trail → note chain integrity = VALID and the block count.',
      'Simulate tamper → the chain flips to TAMPERED with the offending seq listed.',
      'Repair → the chain is recomputed and returns to VALID (tamper markers stripped).',
    ],
  },
  {
    title: 'Cut an agent off immediately',
    steps: [
      'Agents → find the agent row → Revoke (or Suspend).',
      'Confirm the deny-inactive-agents guardrail now blocks it (try a request in Agent Runs).',
    ],
  },
  {
    title: 'Assess the blast radius of a dataset outage',
    steps: [
      'Impact → What-if chaos experiment → pick the dataset and kind = Outage → run.',
      'Inspect the affected-subgraph table and the radial graph (root vs affected vs unaffected).',
      'Or use the custom builder to chain several steps into one experiment.',
    ],
  },
  {
    title: 'Run a security posture scan',
    steps: [
      'Monitor → Guardian monitor scan → Run governed scan.',
      'Review findings: criticality, policy gaps and watchlist breaches.',
      'Log breaches to the audit chain from Active alerts.',
    ],
  },
]

function escapeRe(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function highlight(text: string, ql: string): ReactNode {
  if (!ql) return text
  return text.split(new RegExp(`(${escapeRe(ql)})`, 'gi')).map((part, i) =>
    part.toLowerCase() === ql ? <mark key={i}>{part}</mark> : <span key={i}>{part}</span>)
}

function excerpt(text: string, ql: string): ReactNode {
  const i = text.toLowerCase().indexOf(ql)
  if (i === -1) return null
  const start = Math.max(0, i - 30)
  const end = Math.min(text.length, i + ql.length + 70)
  return (
    <span>
      {start > 0 && '…'}
      {text.slice(start, i)}
      <mark>{text.slice(i, i + ql.length)}</mark>
      {text.slice(i + ql.length, end)}
      {end < text.length && '…'}
    </span>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h3>{title}</h3>
      {children}
    </div>
  )
}

export default function Help() {
  const [q, setQ] = useState('')
  const [openQ, setOpenQ] = useState<string | null>(null)
  const ql = q.trim().toLowerCase()

  const match = (...texts: Array<string | undefined>) =>
    !ql || texts.join(' ').toLowerCase().includes(ql)

  const personas = PERSONAS.filter((p) =>
    match(p.name, p.goal, p.pages.map((x) => `${x[0]} ${x[1]}`).join(' '), p.flow.join(' '), p.tips.join(' ')))
  const faqs = FAQS.filter((f) => match(f.q, f.a))
  const pages = PAGES.filter((p) => match(p.page, p.when, p.how))
  const recipes = RECIPES.filter((r) => match(r.title, r.steps.join(' ')))
  const total = personas.length + faqs.length + pages.length + recipes.length

  return (
    <div>
      <PageHeader
        title="Help & User Manual"
        subtitle="Find how your role uses the platform: persona guides, FAQs, page quick reference, and common workflows. Search across everything below."
      />

      <div className="dt-toolbar" style={{ border: '1px solid var(--border)', borderRadius: 10, marginTop: 4 }}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search personas, FAQs, pages, workflows…"
        />
        <span className="dt-count">{q ? `${total} result${total === 1 ? '' : 's'}` : `${total} topics`}</span>
      </div>

      {q && total === 0 && (
        <div style={{ marginTop: 16 }}><Empty message="No help topics match your search." /></div>
      )}

      <Section title="Persona guides">
        <p style={{ color: 'var(--muted)', fontSize: 13, margin: '0 0 12px' }}>
          Pick the persona closest to your job and jump straight to the features you need.
        </p>
        {personas.map((p) => {
          const chipWhy = ql ? p.pages.find(([name, why]) => !name.toLowerCase().includes(ql) && why.toLowerCase().includes(ql)) : undefined
          return (
          <div key={p.name} className="card" style={{ marginBottom: 12 }}>
            <strong>{highlight(p.name, ql)}</strong>
            {chipWhy && (
              <div className="help-snip" style={{ marginTop: 6 }}>{excerpt(chipWhy[1], ql)}</div>
            )}
            <p style={{ color: 'var(--muted)', fontSize: 13, lineHeight: 1.5, margin: '6px 0 10px' }}>{highlight(p.goal, ql)}</p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
              {p.pages.map(([page, why]) => (
                <span key={page} className="chip" title={why}>{highlight(page, ql)}</span>
              ))}
            </div>
            <div style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.7 }}>
              <div style={{ fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>Typical flow</div>
              <ol style={{ margin: '0 0 10px', paddingLeft: 20 }}>
                {p.flow.map((s, i) => <li key={i}>{highlight(s, ql)}</li>)}
              </ol>
              <div style={{ fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>Watch out for</div>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                {p.tips.map((s, i) => <li key={i}>{highlight(s, ql)}</li>)}
              </ul>
            </div>
          </div>
          )
        })}
      </Section>

      <Section title="Frequently asked questions">
        {faqs.map((f) => {
          const answerHit = ql && f.a.toLowerCase().includes(ql)
          return (
          <div key={f.q} className="card" style={{ marginBottom: 8, padding: 12, cursor: 'pointer' }}
            onClick={() => setOpenQ(openQ === f.q ? null : f.q)}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
              <strong style={{ fontSize: 13 }}>{highlight(f.q, ql)}</strong>
              <span className="chip">{openQ === f.q ? '−' : '+'}</span>
            </div>
            {answerHit && (
              <div className="help-snip" style={{ marginTop: 6 }}>{excerpt(f.a, ql)}</div>
            )}
            {openQ === f.q && (
              <p style={{ color: 'var(--muted)', fontSize: 13, lineHeight: 1.6, margin: '8px 0 0' }}>{highlight(f.a, ql)}</p>
            )}
          </div>
          )
        })}
      </Section>

      <Section title="Page quick reference">
        <table className="table">
          <thead>
            <tr><th></th><th>page</th><th>when to use it</th><th>how to use it</th></tr>
          </thead>
          <tbody>
            {pages.map((p) => (
              <tr key={p.page}>
                <td style={{ width: 28 }}>{p.icon}</td>
                <td style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{highlight(p.page, ql)}</td>
                <td style={{ color: 'var(--muted)', fontSize: 13 }}>{highlight(p.when, ql)}</td>
                <td style={{ fontSize: 13 }}>{highlight(p.how, ql)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Common workflows">
        {recipes.map((r) => (
          <div key={r.title} style={{ marginBottom: 12 }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>{highlight(r.title, ql)}</div>
            <ol style={{ margin: '4px 0 0', paddingLeft: 20, color: 'var(--muted)', fontSize: 12, lineHeight: 1.7 }}>
              {r.steps.map((s, i) => <li key={i}>{highlight(s, ql)}</li>)}
            </ol>
          </div>
        ))}
      </Section>
    </div>
  )
}
