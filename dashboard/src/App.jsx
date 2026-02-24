import { useState } from 'react'
import NaturalLanguageQuery from './components/NaturalLanguageQuery'
import RealtimeDashboard from './components/RealtimeDashboard'
import EventsChart from './components/EventsChart'
import { Zap, LayoutDashboard, MessageSquare, Database, ChevronDown } from 'lucide-react'

const TENANTS = [
  { id: 'demo_tenant', label: 'Demo Tenant' },
  { id: 'acme_corp',   label: 'Acme Corp' },
  { id: 'beta_inc',    label: 'Beta Inc' },
]

function TenantSelector({ value, onChange }) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full appearance-none bg-panel border border-border rounded-lg
                   pl-3 pr-8 py-2 text-xs font-mono text-ghost
                   focus:outline-none focus:border-amber cursor-pointer
                   hover:border-muted transition-colors"
      >
        {TENANTS.map(t => (
          <option key={t.id} value={t.id}>{t.label}</option>
        ))}
      </select>
      <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-dim pointer-events-none" />
    </div>
  )
}

export default function App() {
  const [tenant, setTenant]   = useState('demo_tenant')
  const [activeTab, setActive] = useState('query')

  const nav = [
    { id: 'query',     icon: MessageSquare,  label: 'AI Query' },
    { id: 'dashboard', icon: LayoutDashboard, label: 'Live Dashboard' },
  ]

  return (
    <div className="flex h-screen overflow-hidden bg-void">

      {/* ── Sidebar ── */}
      <aside className="w-56 flex-none flex flex-col bg-surface border-r border-border scanlines">
        {/* Logo */}
        <div className="px-5 pt-6 pb-5">
          <div className="flex items-center gap-2.5 mb-1">
            <div className="w-7 h-7 rounded-lg bg-amber flex items-center justify-center flex-none">
              <Zap className="w-4 h-4 text-black" />
            </div>
            <span className="font-display font-700 text-sm text-text tracking-tight">
              StreamIQ
            </span>
          </div>
          <p className="text-xs text-dim pl-9.5">real-time analytics</p>
        </div>

        {/* Live status */}
        <div className="mx-4 mb-4 flex items-center gap-2 px-3 py-2 rounded-lg bg-panel border border-border">
          <div className="live-dot flex-none" />
          <span className="text-xs font-mono text-ghost">pipeline live</span>
        </div>

        <div className="separator mx-4 mb-4" />

        {/* Nav */}
        <nav className="flex-1 px-3 space-y-1">
          {nav.map(({ id, icon: Icon, label }) => (
            <button
              key={id}
              onClick={() => setActive(id)}
              className={`nav-item ${activeTab === id ? 'active' : ''}`}
            >
              <Icon className="w-4 h-4 flex-none" />
              {label}
            </button>
          ))}
        </nav>

        {/* Tenant selector */}
        <div className="p-4 border-t border-border">
          <p className="text-xs text-dim mb-2 font-mono uppercase tracking-widest">Tenant</p>
          <TenantSelector value={tenant} onChange={setTenant} />
        </div>

        {/* Stats callout */}
        <div className="mx-4 mb-5 p-3 rounded-lg border border-amber/20 bg-amber/5">
          <p className="text-xs font-display font-600 text-amber mb-1">37% cost saved</p>
          <p className="text-xs text-dim leading-relaxed">vs Claude's $35K baseline. ClickHouse-only OLAP, ARM Graviton2, Fargate Spot.</p>
        </div>
      </aside>

      {/* ── Main ── */}
      <div className="flex-1 flex flex-col overflow-hidden">

        {/* Top bar */}
        <header className="flex-none flex items-center justify-between px-8 py-4 border-b border-border bg-surface/60 backdrop-blur">
          <div>
            <h1 className="font-display font-700 text-base text-text tracking-tight">
              {activeTab === 'query' ? 'AI Analytics — Natural Language → SQL' : 'Live Pipeline Dashboard'}
            </h1>
            <p className="text-xs text-dim mt-0.5">
              {activeTab === 'query'
                ? 'Ask anything about your data. Template-matched ClickHouse SQL, executed in real time.'
                : '5-second refresh · Kafka → Flink → ClickHouse · <2.3s p95 end-to-end'}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-panel border border-border">
              <Database className="w-3.5 h-3.5 text-cyan" />
              <span className="text-xs font-mono text-ghost">ClickHouse · {tenant}</span>
            </div>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-y-auto p-8 space-y-6">
          {activeTab === 'query' && (
            <NaturalLanguageQuery customerId={tenant} />
          )}
          {activeTab === 'dashboard' && (
            <>
              <RealtimeDashboard customerId={tenant} />
              <EventsChart customerId={tenant} />
            </>
          )}
        </main>

        {/* Footer */}
        <footer className="flex-none px-8 py-3 border-t border-border flex items-center justify-between">
          <p className="text-xs font-mono text-dim">
            50 Kafka partitions · PyFlink Fargate Spot · ARM Graviton2 · Bloom filter exactly-once
          </p>
          <p className="text-xs font-mono text-dim">
            <span className="text-amber">45ms</span> p95 ingest ·{' '}
            <span className="text-amber">2.3s</span> p95 e2e ·{' '}
            <span className="text-amber">65M</span> events/day verified
          </p>
        </footer>
      </div>
    </div>
  )
}
