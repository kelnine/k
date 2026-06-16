import { useCallback, useEffect, useRef, useState } from 'react'
import { BinanceAdapter } from '../data/binance'
import { DemoAdapter } from '../data/demo'
import type { DataAdapter, SymbolInfo, Timeframe } from '../data/types'
import { detectStructureBreaks } from '../../bot/smc-signals'
import type { StructureBreak } from '../../bot/smc-signals'

// ── types ─────────────────────────────────────────────────────────────────────

export interface Signal {
  id: string
  symbol: string
  tvSymbol: string // e.g. "BINANCE:BTCUSDT"
  side: 'bull' | 'bear'
  breakType: 'BOS' | 'CHoCH'
  level: number
  entry: number
  stop: number
  t1: number
  t2: number
  t3: number
  obTop: number
  obBottom: number
  barAge: number
  tf: string
}

function toSignal(symbol: string, tf: string, sb: StructureBreak, total: number): Signal {
  const { side, level, obTop, obBottom, breakType, breakBar } = sb
  const buf = 0.0005
  const entry = side === 'bull' ? level * (1 + buf) : level * (1 - buf)
  const stop = side === 'bull' ? obBottom * (1 - buf) : obTop * (1 + buf)
  const risk = Math.abs(entry - stop)
  const dir = side === 'bull' ? 1 : -1
  return {
    id: `${symbol}:${tf}:${side}:${level.toFixed(4)}:${breakBar}`,
    symbol,
    tvSymbol: `BINANCE:${symbol}`,
    side,
    breakType,
    level,
    entry,
    stop,
    t1: entry + dir * 0.5 * risk,
    t2: entry + dir * 1.0 * risk,
    t3: entry + dir * 2.0 * risk,
    obTop,
    obBottom,
    barAge: total - 1 - breakBar,
    tf,
  }
}

async function fetchSignals(adapter: DataAdapter, symbol: string, tf: Timeframe): Promise<Signal[]> {
  const candles = await adapter.fetchCandles(symbol, tf, 150)
  const breaks = detectStructureBreaks(candles, 5)
  return breaks.slice(-3).map((sb) => toSignal(symbol, tf, sb, candles.length)).reverse()
}

// ── formatting ────────────────────────────────────────────────────────────────

function p(n: number): string {
  const d = n >= 1000 ? 2 : n >= 10 ? 3 : n >= 1 ? 4 : 6
  return n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
}

// ── TradingView chart ─────────────────────────────────────────────────────────

declare global {
  interface Window {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    TradingView: any
  }
}

const TF_TV: Record<string, string> = { '1m': '1', '5m': '5', '15m': '15', '1h': '60', '4h': '240', '1d': 'D' }

function TvChart({ symbol, tf }: { symbol: string; tf: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const widgetRef = useRef<ReturnType<typeof window.TradingView.widget> | null>(null)
  const idRef = useRef(`tv_${Math.random().toString(36).slice(2)}`)

  useEffect(() => {
    const id = idRef.current
    function init() {
      if (!containerRef.current || !window.TradingView) return
      widgetRef.current = new window.TradingView.widget({
        container_id: id,
        autosize: true,
        symbol,
        interval: TF_TV[tf] ?? '60',
        timezone: 'Etc/UTC',
        theme: 'dark',
        style: '1',
        locale: 'en',
        toolbar_bg: '#141923',
        hide_side_toolbar: false,
        allow_symbol_change: true,
        save_image: false,
        hide_legend: false,
        withdateranges: true,
      })
    }

    if (window.TradingView) {
      init()
    } else {
      const s = document.createElement('script')
      s.src = 'https://s3.tradingview.com/tv.js'
      s.onload = init
      document.head.appendChild(s)
    }

    return () => {
      if (containerRef.current) containerRef.current.innerHTML = ''
      widgetRef.current = null
    }
  }, [symbol, tf])

  return <div ref={containerRef} id={idRef.current} className="fc-tv-chart" />
}

// ── symbol search (Binance pairs) ─────────────────────────────────────────────

function SymbolSearch({
  adapter,
  active,
  onAdd,
  onRemove,
}: {
  adapter: DataAdapter
  active: string[]
  onAdd: (s: string) => void
  onRemove: (s: string) => void
}) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SymbolInfo[]>([])
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    const t = setTimeout(async () => {
      const r = await adapter.searchSymbols(query)
      if (!cancelled) setResults(r.slice(0, 14))
    }, 120)
    return () => { cancelled = true; clearTimeout(t) }
  }, [adapter, query])

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  return (
    <div className="fc-search" ref={ref}>
      <input
        className="fc-search-input"
        placeholder="＋ Add pair…"
        value={query}
        onFocus={() => setOpen(true)}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && results[0]) { onAdd(results[0].symbol); setQuery(''); setOpen(false) }
          if (e.key === 'Escape') setOpen(false)
        }}
      />
      {open && results.length > 0 && (
        <div className="fc-search-drop">
          {results.map((r) => {
            const on = active.includes(r.symbol)
            return (
              <div key={r.symbol} className={`fc-search-item${on ? ' on' : ''}`} onClick={() => {
                on ? onRemove(r.symbol) : onAdd(r.symbol)
                setQuery(''); setOpen(false)
              }}>
                <span className="fc-search-sym">{r.symbol}</span>
                <span className="fc-search-desc">{r.description}</span>
                {on && <span className="fc-check">✓</span>}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── signal card ───────────────────────────────────────────────────────────────

function SignalCard({
  sig,
  active,
  onClick,
}: {
  sig: Signal
  active: boolean
  onClick: () => void
}) {
  const base = sig.symbol.replace(/USDT$/, '')
  const bull = sig.side === 'bull'
  const color = bull ? '#26a69a' : '#ef5350'
  const setup = `${sig.breakType} ${bull ? 'Bull' : 'Bear'}`
  const risk = Math.abs(sig.entry - sig.stop)

  return (
    <div
      className={`fc-card${active ? ' fc-card-active' : ''}`}
      style={{ '--card-color': color } as React.CSSProperties}
      onClick={onClick}
    >
      {/* top strip */}
      <div className="fc-card-strip" style={{ background: color }} />

      {/* head */}
      <div className="fc-head">
        <div className="fc-head-left">
          <span className="fc-sym">${base}</span>
          <span className="fc-tf-tag">{sig.tf}</span>
        </div>
        <div className="fc-head-right">
          <span className="fc-setup-tag" style={{ color, border: `1px solid ${color}33` }}>{setup}</span>
          <span className={`fc-dir-tag ${sig.side}`}>{bull ? '▲ LONG' : '▼ SHORT'}</span>
        </div>
      </div>

      {/* level */}
      <div className="fc-level">
        <span className="fc-level-label">Level</span>
        <span className="fc-level-val">{p(sig.level)}</span>
      </div>

      {/* entry / stop */}
      <div className="fc-es-row">
        <div className="fc-es-col">
          <span>Entry</span>
          <b>{p(sig.entry)}</b>
        </div>
        <div className="fc-es-col">
          <span>Stop</span>
          <b style={{ color: '#ef5350' }}>{p(sig.stop)}</b>
        </div>
        <div className="fc-es-col">
          <span>Risk</span>
          <b>{p(risk)}</b>
        </div>
      </div>

      {/* targets */}
      <div className="fc-tgt-row">
        {[
          { label: 'T1', val: sig.t1, r: '0.5R' },
          { label: 'T2', val: sig.t2, r: '1R' },
          { label: 'T3', val: sig.t3, r: '2R' },
        ].map(({ label, val, r }) => (
          <div key={label} className="fc-tgt" style={{ borderColor: `${color}55` }}>
            <span style={{ color }}>{label}</span>
            <b>{p(val)}</b>
            <em>{r}</em>
          </div>
        ))}
      </div>

      {/* footer */}
      <div className="fc-card-foot">
        <span>OB {p(sig.obBottom)} — {p(sig.obTop)}</span>
        <span>{sig.barAge}h ago  →</span>
      </div>
    </div>
  )
}

// ── skeleton ──────────────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="fc-card fc-skel">
      <div className="fc-skel-bar" />
      <div className="fc-skel-line" style={{ width: '55%', height: 18 }} />
      <div className="fc-skel-line" style={{ width: '80%', height: 10, marginTop: 4 }} />
      <div className="fc-skel-line" style={{ width: '100%', height: 52, marginTop: 8, borderRadius: 6 }} />
    </div>
  )
}

// ── countdown ─────────────────────────────────────────────────────────────────

function Countdown({ secs, onFire }: { secs: number; onFire: () => void }) {
  const [left, setLeft] = useState(secs)
  const fire = useRef(onFire)
  fire.current = onFire

  useEffect(() => { setLeft(secs) }, [secs])

  useEffect(() => {
    const t = setInterval(() => setLeft((n) => {
      if (n <= 1) { fire.current(); return secs }
      return n - 1
    }), 1000)
    return () => clearInterval(t)
  }, [secs])

  return <span className="fc-cd">{left}s</span>
}

// ── main ──────────────────────────────────────────────────────────────────────

const STORAGE_KEY = 'sigfeed:v2:symbols'
const DEFAULT_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT']

function loadSymbols() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '') as string[] } catch { return DEFAULT_SYMBOLS }
}

export function FeedApp() {
  const [symbols, setSymbols] = useState<string[]>(loadSymbols)
  const [tf, setTf] = useState<Timeframe>('1h')
  const [signals, setSignals] = useState<Signal[]>([])
  const [loading, setLoading] = useState(true)
  const [adapter, setAdapter] = useState<DataAdapter | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [chartSymbol, setChartSymbol] = useState('BINANCE:BTCUSDT')
  const [chartTf, setChartTf] = useState<Timeframe>(tf)
  const [activeId, setActiveId] = useState<string | null>(null)

  useEffect(() => { localStorage.setItem(STORAGE_KEY, JSON.stringify(symbols)) }, [symbols])

  useEffect(() => {
    BinanceAdapter.available(3000).then((ok) => setAdapter(ok ? new BinanceAdapter() : new DemoAdapter()))
  }, [])

  const load = useCallback(async () => {
    if (!adapter) return
    setLoading(true)
    const live: Signal[] = []
    await Promise.allSettled(symbols.map(async (sym) => {
      try {
        const sigs = await fetchSignals(adapter, sym, tf)
        live.push(...sigs)
        setSignals([...live].sort((a, b) => a.barAge - b.barAge).slice(0, 30))
      } catch {/* skip */}
    }))
    setLoading(false)
  }, [adapter, symbols, tf])

  useEffect(() => { load() }, [load, refreshKey])

  function pickSignal(sig: Signal) {
    setActiveId(sig.id)
    setChartSymbol(sig.tvSymbol)
    setChartTf(sig.tf as Timeframe)
  }

  const isLive = adapter instanceof BinanceAdapter

  return (
    <div className="fc-app">
      {/* ── topbar ── */}
      <header className="fc-bar">
        <div className="fc-logo">⚡ Signal Feed</div>

        {adapter && (
          <SymbolSearch
            adapter={adapter}
            active={symbols}
            onAdd={(s) => setSymbols((p) => p.includes(s) ? p : [...p, s])}
            onRemove={(s) => setSymbols((p) => p.length > 1 ? p.filter((x) => x !== s) : p)}
          />
        )}

        <div className="fc-tf-group">
          {(['15m', '1h', '4h', '1d'] as Timeframe[]).map((t) => (
            <button key={t} className={`fc-tf-btn${tf === t ? ' on' : ''}`} onClick={() => setTf(t)}>{t}</button>
          ))}
        </div>

        <div className="fc-bar-right">
          <span className={`fc-live-dot ${isLive ? 'live' : 'demo'}`}>
            {isLive ? '● Live' : '● Demo'}
          </span>
          <button className="fc-icon-btn" onClick={() => setRefreshKey((k) => k + 1)} disabled={loading} title="Refresh">
            {loading ? '…' : '↻'}
          </button>
          {!loading && <Countdown secs={60} onFire={() => setRefreshKey((k) => k + 1)} />}
        </div>
      </header>

      {/* ── watchlist pills ── */}
      <div className="fc-pills">
        {symbols.map((s) => (
          <span key={s} className="fc-pill">
            {s.replace(/USDT$/, '')}
            <button className="fc-pill-x" onClick={() => setSymbols((p) => p.length > 1 ? p.filter((x) => x !== s) : p)}>×</button>
          </span>
        ))}
      </div>

      {/* ── split body ── */}
      <div className="fc-body">
        {/* chart */}
        <div className="fc-chart-panel">
          <TvChart symbol={chartSymbol} tf={chartTf} />
        </div>

        {/* signals */}
        <div className="fc-feed-panel">
          {loading && signals.length === 0 && Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} />)}
          {!loading && signals.length === 0 && (
            <div className="fc-empty">No signals — try more pairs or a wider timeframe</div>
          )}
          {signals.map((sig) => (
            <SignalCard
              key={sig.id}
              sig={sig}
              active={sig.id === activeId}
              onClick={() => pickSignal(sig)}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
