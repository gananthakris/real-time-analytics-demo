import { useState, useRef, useEffect } from 'react'
import { Send, Loader2, Code2, Lightbulb, ChevronRight, Terminal, Sparkles } from 'lucide-react'

const API_URL = 'http://localhost:8001'

const EXAMPLES = [
  'Find users who abandoned cart after viewing pricing 3+ times',
  'Show me the top 10 pages by views today',
  'What are the most common events in the last hour?',
  'Show me conversion rate for each step in signup funnel',
]

/* ── SQL Syntax Highlighter ────────────────────────────── */
const KEYWORDS = [
  'SELECT','FROM','WHERE','GROUP BY','ORDER BY','HAVING','LIMIT',
  'AND','OR','NOT','IN','AS','DISTINCT','ON','JOIN','LEFT','INNER',
  'INTERVAL','DAY','HOUR','MINUTE','MONTH',
  'COUNT','MAX','MIN','AVG','SUM','ROUND',
]
const FUNCTIONS = [
  'countIf','uniq','uniqExact','toStartOfHour','toStartOfMinute',
  'toDate','now','today','JSONExtractString','JSONExtractInt',
]

function highlightSQL(sql) {
  if (!sql) return null
  const lines = sql.split('\n')
  return lines.map((line, li) => {
    const parts = []
    let remaining = line
    let key = 0
    while (remaining.length > 0) {
      // Comment
      if (remaining.startsWith('--')) {
        parts.push(<span key={key++} className="sql-comment">{remaining}</span>)
        remaining = ''
        continue
      }
      // String literal
      const strMatch = remaining.match(/^'[^']*'/)
      if (strMatch) {
        parts.push(<span key={key++} className="sql-string">{strMatch[0]}</span>)
        remaining = remaining.slice(strMatch[0].length)
        continue
      }
      // Number
      const numMatch = remaining.match(/^\b\d+\b/)
      if (numMatch) {
        parts.push(<span key={key++} className="sql-number">{numMatch[0]}</span>)
        remaining = remaining.slice(numMatch[0].length)
        continue
      }
      // Function (case-sensitive)
      let matched = false
      for (const fn of FUNCTIONS) {
        if (remaining.startsWith(fn + '(')) {
          parts.push(<span key={key++} className="sql-fn">{fn}</span>)
          remaining = remaining.slice(fn.length)
          matched = true
          break
        }
      }
      if (matched) continue
      // Keyword (case-insensitive, whole word)
      for (const kw of KEYWORDS) {
        if (remaining.toUpperCase().startsWith(kw) &&
            !/[A-Z0-9_]/i.test(remaining[kw.length] || '')) {
          parts.push(<span key={key++} className="sql-keyword">{remaining.slice(0, kw.length)}</span>)
          remaining = remaining.slice(kw.length)
          matched = true
          break
        }
      }
      if (matched) continue
      // Default: consume one char
      parts.push(remaining[0])
      remaining = remaining.slice(1)
    }
    return <div key={li}>{parts}</div>
  })
}

/* ── Data Table ──────────────────────────────────────── */
function ResultTable({ data }) {
  if (!data || data.length === 0) return null
  const cols = Object.keys(data[0])
  return (
    <div className="overflow-x-auto">
      <table className="data-table w-full">
        <thead>
          <tr>
            {cols.map(c => <th key={c}>{c.replace(/_/g, ' ')}</th>)}
          </tr>
        </thead>
        <tbody>
          {data.slice(0, 50).map((row, i) => (
            <tr key={i} className={i === 0 ? 'result-row-new' : ''}>
              {cols.map(c => (
                <td key={c}>
                  {typeof row[c] === 'object' ? JSON.stringify(row[c]) : String(row[c] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ── Main Component ──────────────────────────────────── */
export default function NaturalLanguageQuery({ customerId }) {
  const [query, setQuery]   = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult]  = useState(null)
  const [error, setError]   = useState(null)
  const [showSQL, setShowSQL] = useState(true)
  const textareaRef = useRef(null)
  const resultsRef  = useRef(null)

  useEffect(() => {
    textareaRef.current?.focus()
  }, [])

  const submit = async (q) => {
    const text = (q || query).trim()
    if (!text) return
    setQuery(text)
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await fetch(`${API_URL}/ai/query`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ query: text, customer_id: customerId, execute: true }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      if (data.success) {
        setResult(data)
        setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100)
      } else {
        setError(data.error || 'Query failed')
      }
    } catch (e) {
      setError(`${e.message}`)
    } finally {
      setLoading(false)
    }
  }

  const handleKey = (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit()
  }

  return (
    <div className="space-y-5 animate-fade-up">

      {/* ── Query input ── */}
      <div className="panel p-5">
        <div className="flex items-center gap-2 mb-4">
          <Sparkles className="w-4 h-4 text-amber" />
          <span className="text-sm font-display font-600 text-text">Natural Language Query</span>
          <span className="ml-auto text-xs font-mono text-dim">⌘ + Enter to run</span>
        </div>

        <div className="relative">
          <textarea
            ref={textareaRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKey}
            placeholder="e.g. Find users who viewed pricing 3+ times but didn't sign up..."
            rows={3}
            className="query-textarea w-full bg-panel border border-border rounded-lg
                       px-4 py-3 pr-36 text-sm text-text font-sans
                       placeholder:text-dim resize-none
                       transition-all duration-200"
          />
          <button
            onClick={() => submit()}
            disabled={loading || !query.trim()}
            className="btn-amber absolute bottom-3 right-3 flex items-center gap-2
                       px-4 py-2 rounded-lg text-xs font-display font-600"
          >
            {loading
              ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Analyzing</>
              : <><Send className="w-3.5 h-3.5" /> Ask AI</>
            }
          </button>
        </div>

        {/* Example chips */}
        <div className="flex flex-wrap gap-2 mt-3">
          <span className="text-xs text-dim self-center">Try:</span>
          {EXAMPLES.map((ex, i) => (
            <button key={i} className="chip" onClick={() => submit(ex)}>
              {ex}
            </button>
          ))}
        </div>
      </div>

      {/* ── Error ── */}
      {error && (
        <div className="panel p-4 border-red/40 stagger-1">
          <div className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-red flex-none" />
            <span className="text-xs font-mono text-red">{error}</span>
          </div>
        </div>
      )}

      {/* ── Results ── */}
      {result && (
        <div ref={resultsRef} className="space-y-4">

          {/* Row 1: SQL + Explanation */}
          <div className="grid grid-cols-2 gap-4 stagger-1">

            {/* SQL panel */}
            <div className="panel overflow-hidden">
              <div
                className="flex items-center gap-2 px-5 py-3.5 border-b border-border cursor-pointer hover:bg-panel/50 transition-colors"
                onClick={() => setShowSQL(s => !s)}
              >
                <Terminal className="w-4 h-4 text-amber flex-none" />
                <span className="text-sm font-display font-600 text-text">Generated SQL</span>
                <span className="ml-auto text-xs font-mono text-dim">
                  {result.execution_time_ms?.toFixed(0)}ms
                </span>
                <ChevronRight className={`w-4 h-4 text-dim transition-transform ${showSQL ? 'rotate-90' : ''}`} />
              </div>
              {showSQL && (
                <pre className="p-5 text-xs font-mono leading-relaxed overflow-x-auto text-ghost bg-panel/40">
                  {highlightSQL(result.sql)}
                </pre>
              )}
            </div>

            {/* Explanation panel */}
            <div className="panel p-5 flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <Lightbulb className="w-4 h-4 text-cyan flex-none" />
                <span className="text-sm font-display font-600 text-text">What this does</span>
              </div>
              <p className="text-sm text-ghost leading-relaxed">{result.explanation}</p>
              {result.insights && (
                <>
                  <div className="separator" />
                  <p className="text-xs text-ghost leading-relaxed italic">{result.insights}</p>
                </>
              )}
            </div>
          </div>

          {/* Results table */}
          {result.data && result.data.length > 0 && (
            <div className="panel overflow-hidden stagger-2">
              <div className="flex items-center gap-3 px-5 py-3.5 border-b border-border">
                <Code2 className="w-4 h-4 text-green flex-none" />
                <span className="text-sm font-display font-600 text-text">
                  Results
                </span>
                <span className="ml-1 px-2 py-0.5 rounded-full bg-green/10 text-green text-xs font-mono">
                  {result.data.length} rows
                </span>
              </div>
              <ResultTable data={result.data} />
            </div>
          )}

          {result.data && result.data.length === 0 && (
            <div className="panel p-8 flex items-center justify-center stagger-2">
              <p className="text-sm text-dim font-mono">No rows matched — try adjusting the time range or filters.</p>
            </div>
          )}

          {/* Related queries */}
          {result.related_queries?.length > 0 && (
            <div className="panel p-5 stagger-3">
              <p className="text-xs font-mono text-dim uppercase tracking-widest mb-3">Continue exploring</p>
              <div className="flex flex-wrap gap-2">
                {result.related_queries.map((q, i) => (
                  <button key={i} className="chip" onClick={() => submit(q)}>
                    <ChevronRight className="w-3 h-3 mr-1 opacity-50" />
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
