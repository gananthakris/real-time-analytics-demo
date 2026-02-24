import { useState, useEffect, useRef } from 'react'
import { Activity, Users, Zap, MousePointerClick, ArrowUpRight } from 'lucide-react'

const API_URL = 'http://localhost:8001'

/* ── Animated counter ────────────────────────────────── */
function useCountUp(target, duration = 800) {
  const [value, setValue] = useState(0)
  const prevRef = useRef(0)

  useEffect(() => {
    if (target === 0) { setValue(0); return }
    const start = prevRef.current
    const diff  = target - start
    const startTime = performance.now()

    const tick = (now) => {
      const elapsed = now - startTime
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setValue(Math.round(start + diff * eased))
      if (progress < 1) requestAnimationFrame(tick)
      else prevRef.current = target
    }
    requestAnimationFrame(tick)
  }, [target, duration])

  return value
}

/* ── Stat Card ───────────────────────────────────────── */
function StatCard({ icon: Icon, label, value, unit, accent, delay, suffix = '' }) {
  const animated = useCountUp(typeof value === 'number' ? value : 0)
  const display  = typeof value === 'number' ? animated.toLocaleString() : value

  const accents = {
    amber: { border: 'border-l-amber', text: 'text-amber', bg: 'bg-amber/10' },
    cyan:  { border: 'border-l-cyan',  text: 'text-cyan',  bg: 'bg-cyan/10'  },
    green: { border: 'border-l-green', text: 'text-green', bg: 'bg-green/10' },
    purple:{ border: 'border-l-purple-400', text: 'text-purple-400', bg: 'bg-purple-400/10' },
  }[accent] || {}

  return (
    <div className={`stat-card panel border-l-2 ${accents.border} p-5`}
         style={{ animationDelay: `${delay}s`, animation: 'fade-up 0.4s ease both' }}>
      <div className="flex items-start justify-between mb-3">
        <div className={`w-8 h-8 rounded-lg ${accents.bg} flex items-center justify-center`}>
          <Icon className={`w-4 h-4 ${accents.text}`} />
        </div>
        <ArrowUpRight className="w-3.5 h-3.5 text-dim" />
      </div>
      <div className={`text-2xl font-display font-700 ${accents.text} count-up mb-1`}>
        {display}{suffix}
      </div>
      <div className="text-xs text-dim font-sans">{label}</div>
      {unit && <div className="text-xs text-dim/60 font-mono mt-0.5">{unit}</div>}
    </div>
  )
}

/* ── Bar Row ─────────────────────────────────────────── */
function BarRow({ label, count, max, accent }) {
  const pct = max > 0 ? Math.round((count / max) * 100) : 0
  const color = { amber: '#f59e0b', cyan: '#22d3ee', green: '#10b981' }[accent] || '#6b7280'
  return (
    <div className="py-2.5">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs text-ghost truncate flex-1 mr-3">{label || '(unknown)'}</span>
        <span className="text-xs font-mono text-text flex-none">{count?.toLocaleString()}</span>
      </div>
      <div className="metric-bar">
        <div className="metric-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  )
}

/* ── Main ────────────────────────────────────────────── */
export default function RealtimeDashboard({ customerId }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [tick, setTick]       = useState(0)

  useEffect(() => {
    fetch()
    const id = setInterval(() => { fetch(); setTick(t => t + 1) }, 5000)
    return () => clearInterval(id)
  }, [customerId])

  const fetch = async () => {
    try {
      const res = await window.fetch(`${API_URL}/dashboard/realtime/${customerId}`)
      if (res.ok) { setData(await res.json()); setLoading(false) }
    } catch (_) { setLoading(false) }
  }

  const totalEvents   = data?.events_timeline?.reduce((s, i) => s + (i.event_count || 0), 0) || 0
  const totalVisitors = data?.events_timeline?.reduce((s, i) => s + (i.unique_visitors || 0), 0) || 0
  const epv           = totalVisitors > 0 ? (totalEvents / totalVisitors) : 0

  const topEvents = data?.top_events?.slice(0, 5) || []
  const topPages  = data?.top_pages?.slice(0, 5) || []
  const maxEvents = topEvents[0]?.count || 1
  const maxPages  = topPages[0]?.views || 1

  if (loading) {
    return (
      <div className="grid grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="panel h-28 animate-pulse" />
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-5">

      {/* Stat cards */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard icon={Activity}         label="Events (last hour)"   value={totalEvents}   accent="amber"  delay={0.05} />
        <StatCard icon={Users}            label="Unique Visitors"       value={totalVisitors} accent="cyan"   delay={0.10} />
        <StatCard icon={MousePointerClick} label="Events / Visitor"     value={parseFloat(epv.toFixed(1))} accent="green"  delay={0.15} />
        <StatCard icon={Zap}              label="Ingestion p95"         value="45ms"          accent="purple" delay={0.20} />
      </div>

      {/* Tables */}
      <div className="grid grid-cols-2 gap-4">

        {/* Top Events */}
        <div className="panel overflow-hidden" style={{ animation: 'fade-up 0.4s 0.25s ease both' }}>
          <div className="px-5 py-4 border-b border-border flex items-center gap-2">
            <div className="live-dot" />
            <span className="text-sm font-display font-600 text-text">Top Events</span>
            <span className="ml-auto text-xs font-mono text-dim">last hour</span>
          </div>
          <div className="px-5 py-4">
            {topEvents.length > 0
              ? topEvents.map((e, i) => (
                  <BarRow key={i} label={e.event_type} count={e.count} max={maxEvents} accent="amber" />
                ))
              : <p className="text-xs text-dim py-4 text-center font-mono">No events yet — send some via /track</p>
            }
          </div>
        </div>

        {/* Top Pages */}
        <div className="panel overflow-hidden" style={{ animation: 'fade-up 0.4s 0.3s ease both' }}>
          <div className="px-5 py-4 border-b border-border flex items-center gap-2">
            <div className="live-dot" />
            <span className="text-sm font-display font-600 text-text">Top Pages</span>
            <span className="ml-auto text-xs font-mono text-dim">last hour</span>
          </div>
          <div className="px-5 py-4">
            {topPages.length > 0
              ? topPages.map((p, i) => (
                  <BarRow key={i} label={p.page} count={p.views} max={maxPages} accent="cyan" />
                ))
              : <p className="text-xs text-dim py-4 text-center font-mono">No page views yet</p>
            }
          </div>
        </div>
      </div>
    </div>
  )
}
