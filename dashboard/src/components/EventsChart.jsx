import { useState, useEffect } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'

const API_URL = 'http://localhost:8001'

/* ── Custom Tooltip ────────────────────────────────── */
function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="panel px-4 py-3 text-xs font-mono border-amber/30 space-y-1 shadow-xl">
      <p className="text-dim mb-2">{label}</p>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-3">
          <span className="w-2 h-2 rounded-full flex-none" style={{ background: p.color }} />
          <span className="text-ghost">{p.name}</span>
          <span className="ml-auto font-600" style={{ color: p.color }}>{p.value?.toLocaleString()}</span>
        </div>
      ))}
    </div>
  )
}

export default function EventsChart({ customerId }) {
  const [data, setData] = useState([])

  useEffect(() => {
    fetchData()
    const id = setInterval(fetchData, 10000)
    return () => clearInterval(id)
  }, [customerId])

  const fetchData = async () => {
    try {
      const res = await fetch(`${API_URL}/dashboard/realtime/${customerId}`)
      if (!res.ok) return
      const json = await res.json()
      const formatted = (json.events_timeline || [])
        .map(item => ({
          time:     new Date(item.minute).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
          events:   item.event_count || 0,
          visitors: item.unique_visitors || 0,
        }))
        .reverse()
        .slice(-30)
      setData(formatted)
    } catch (_) {}
  }

  const maxVal = Math.max(...data.map(d => d.events), 1)

  return (
    <div className="panel overflow-hidden"
         style={{ animation: 'fade-up 0.4s 0.35s ease both' }}>
      <div className="flex items-center gap-3 px-6 py-4 border-b border-border">
        <span className="text-sm font-display font-600 text-text">Event Stream</span>
        <span className="text-xs font-mono text-dim">last 30 minutes</span>
        <div className="ml-auto flex items-center gap-4 text-xs font-mono">
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-0.5 rounded-full inline-block" style={{ background: '#f59e0b' }} />
            <span className="text-dim">events</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-0.5 rounded-full inline-block" style={{ background: '#22d3ee' }} />
            <span className="text-dim">visitors</span>
          </span>
        </div>
      </div>

      <div className="px-2 pt-4 pb-2">
        {data.length > 0 ? (
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={data} margin={{ top: 4, right: 16, bottom: 0, left: -8 }}>
              <defs>
                <linearGradient id="gEvents" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"   stopColor="#f59e0b" stopOpacity={0.25} />
                  <stop offset="100%" stopColor="#f59e0b" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gVisitors" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"   stopColor="#22d3ee" stopOpacity={0.2} />
                  <stop offset="100%" stopColor="#22d3ee" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid
                strokeDasharray="1 4"
                stroke="#1e2d3d"
                vertical={false}
              />
              <XAxis
                dataKey="time"
                tick={{ fontSize: 10, fill: '#6b7280', fontFamily: 'JetBrains Mono' }}
                axisLine={false}
                tickLine={false}
                interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fontSize: 10, fill: '#6b7280', fontFamily: 'JetBrains Mono' }}
                axisLine={false}
                tickLine={false}
                width={30}
              />
              <Tooltip content={<CustomTooltip />} cursor={{ stroke: '#1e2d3d', strokeWidth: 1 }} />
              {maxVal > 0 && (
                <ReferenceLine
                  y={maxVal}
                  stroke="#f59e0b"
                  strokeDasharray="3 6"
                  strokeOpacity={0.3}
                />
              )}
              <Area
                type="monotone"
                dataKey="events"
                name="Total Events"
                stroke="#f59e0b"
                strokeWidth={1.5}
                fill="url(#gEvents)"
                dot={false}
                activeDot={{ r: 3, fill: '#f59e0b', stroke: '#080c10', strokeWidth: 2 }}
              />
              <Area
                type="monotone"
                dataKey="visitors"
                name="Unique Visitors"
                stroke="#22d3ee"
                strokeWidth={1.5}
                fill="url(#gVisitors)"
                dot={false}
                activeDot={{ r: 3, fill: '#22d3ee', stroke: '#080c10', strokeWidth: 2 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-[220px] flex items-center justify-center">
            <p className="text-xs font-mono text-dim">
              Waiting for stream data · send events via POST /track
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
