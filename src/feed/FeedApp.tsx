import { useCallback, useEffect, useRef, useState } from 'react'
import { BinanceAdapter } from '../data/binance'
import { DemoAdapter } from '../data/demo'
import type { DataAdapter, Timeframe } from '../data/types'
import { detectStructureBreaks } from '../../bot/smc-signals'
import type { StructureBreak } from '../../bot/smc-signals'

// ── types ─────────────────────────────────────────────────────────────────────

export type Side = 'bull' | 'bear'

export interface Signal {
  id: string
  symbol: string
  side: Side
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

async function fetchSignals(
  adapter: DataAdapter,
  symbol: string,
  tf: Timeframe,
): Promise<Signal[]> {
  const candles = await adapter.fetchCandles(symbol, tf, 150)
  const breaks = detectStructureBreaks(candles, 5)
  return breaks
    .slice(-3)
    .map((sb) => toSignal(symbol, tf, sb, candles.length))
    .reverse()
}

// ── formatting ────────────────────────────────────────────────────────────────

function p(n: number): string {
  const d = n >= 1000 ? 2 : n >= 10 ? 3 : n >= 1 ? 4 : 6
  return n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
}

// ── constants ─────────────────────────────────────────────────────────────────

const ALL_SYMBOLS = [
  'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT',
  'XRPUSDT', 'DOGEUSDT', 'ADAUSDT', 'AVAXUSDT',
  'LINKUSDT', 'DOTUSDT',
]

const REFRESH_SEC = 60

// ── card ──────────────────────────────────────────────────────────────────────

function SignalCard({ sig }: { sig: Signal }) {
  const base = sig.symbol.replace(/USDT$/, '')
  const bull = sig.side === 'bull'
  const color = bull ? '#26a69a' : '#ef5350'
  const bgColor = bull ? 'rgba(38,166,154,0.06)' : 'rgba(239,83,80,0.06)'
  const setup = `${sig.breakType} ${bull ? 'Bullish' : 'Bearish'}`
  const risk = Math.abs(sig.entry - sig.stop)
  const rr = [
    { label: 'T1', val: sig.t1, r: '0.5R' },
    { label: 'T2', val: sig.t2, r: '1R' },
    { label: 'T3', val: sig.t3, r: '2R' },
  ]

  return (
    <div className="fc-card" style={{ borderTopColor: color, background: bgColor }}>
      {/* header */}
      <div className="fc-card-header">
        <div className="fc-card-title">
          <span className="fc-sym">${base}</span>
          <span className="fc-tf">{sig.tf}</span>
        </div>
        <div className="fc-card-meta">
          <span className="fc-setup" style={{ color }}>{setup}</span>
          <span className={`fc-dir ${sig.side}`}>{bull ? '▲ LONG' : '▼ SHORT'}</span>
        </div>
      </div>

      {/* entry / stop */}
      <div className="fc-es">
        <div className="fc-es-item">
          <span>Entry</span>
          <b>{p(sig.entry)}</b>
        </div>
        <div className="fc-es-item">
          <span>Stop</span>
          <b style={{ color: '#ef5350' }}>{p(sig.stop)}</b>
        </div>
        <div className="fc-es-item">
          <span>Risk</span>
          <b>{p(risk)}</b>
        </div>
        <div className="fc-es-item">
          <span>Level</span>
          <b>{p(sig.level)}</b>
        </div>
      </div>

      {/* targets */}
      <div className="fc-targets">
        {rr.map(({ label, val, r }) => (
          <div key={label} className="fc-target" style={{ borderColor: color }}>
            <span className="fc-target-label" style={{ color }}>{label}</span>
            <span className="fc-target-val">{p(val)}</span>
            <span className="fc-target-r">{r}</span>
          </div>
        ))}
      </div>

      {/* footer */}
      <div className="fc-card-footer">
        <span>OB {p(sig.obBottom)} – {p(sig.obTop)}</span>
        <span style={{ color: 'var(--text-dim)' }}>{sig.barAge}h ago</span>
      </div>
    </div>
  )
}

// ── skeleton ──────────────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="fc-card fc-skeleton">
      <div className="fc-skel-line fc-skel-wide" />
      <div className="fc-skel-line fc-skel-mid" />
      <div className="fc-skel-line fc-skel-short" />
    </div>
  )
}

// ── countdown ─────────────────────────────────────────────────────────────────

function Countdown({ secs, onTick }: { secs: number; onTick: () => void }) {
  const [left, setLeft] = useState(secs)
  const cb = useRef(onTick)
  cb.current = onTick

  useEffect(() => {
    setLeft(secs)
  }, [secs])

  useEffect(() => {
    const t = setInterval(() => {
      setLeft((n) => {
        if (n <= 1) { cb.current(); return secs }
        return n - 1
      })
    }, 1000)
    return () => clearInterval(t)
  }, [secs])

  return <span className="fc-countdown">{left}s</span>
}

// ── main app ──────────────────────────────────────────────────────────────────

export function FeedApp() {
  const [symbols, setSymbols] = useState(['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT'])
  const [tf, setTf] = useState<Timeframe>('1h')
  const [signals, setSignals] = useState<Signal[]>([])
  const [loading, setLoading] = useState(true)
  const [adapter, setAdapter] = useState<DataAdapter | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  // resolve adapter once on mount
  useEffect(() => {
    BinanceAdapter.available(3000).then((ok) => {
      setAdapter(ok ? new BinanceAdapter() : new DemoAdapter())
    })
  }, [])

  const load = useCallback(async () => {
    if (!adapter) return
    setLoading(true)
    const live: Signal[] = []

    await Promise.allSettled(
      symbols.map(async (sym) => {
        try {
          const sigs = await fetchSignals(adapter, sym, tf)
          live.push(...sigs)
          const sorted = [...live].sort((a, b) => a.barAge - b.barAge)
          setSignals(sorted.slice(0, 20))
        } catch {/* skip */}
      }),
    )

    setLoading(false)
  }, [adapter, symbols, tf])

  useEffect(() => { load() }, [load, refreshKey])

  function toggleSymbol(s: string) {
    setSymbols((prev) =>
      prev.includes(s)
        ? prev.length > 1 ? prev.filter((x) => x !== s) : prev
        : [...prev, s],
    )
  }

  const isLive = adapter instanceof BinanceAdapter

  return (
    <div className="fc-app">
      {/* ── header ── */}
      <header className="fc-header">
        <div className="fc-brand">
          <span className="fc-bolt">⚡</span>
          <span>Signal Feed</span>
          <span className="fc-badge" style={{ background: isLive ? 'rgba(38,166,154,0.15)' : 'rgba(139,147,163,0.15)', color: isLive ? '#26a69a' : '#8b93a3' }}>
            {isLive ? '● Live' : '● Demo'}
          </span>
        </div>

        <div className="fc-controls">
          {/* timeframe */}
          <div className="fc-tf-group">
            {(['15m', '1h', '4h', '1d'] as Timeframe[]).map((t) => (
              <button
                key={t}
                className={`fc-tf-btn${tf === t ? ' on' : ''}`}
                onClick={() => setTf(t)}
              >
                {t}
              </button>
            ))}
          </div>

          {/* refresh */}
          <button
            className="fc-refresh-btn"
            onClick={() => setRefreshKey((k) => k + 1)}
            disabled={loading}
            title="Refresh"
          >
            {loading ? '…' : '↻'}
          </button>
          {!loading && (
            <Countdown secs={REFRESH_SEC} onTick={() => setRefreshKey((k) => k + 1)} />
          )}
        </div>
      </header>

      {/* ── symbol pills ── */}
      <div className="fc-symbols">
        {ALL_SYMBOLS.map((s) => {
          const base = s.replace(/USDT$/, '')
          const on = symbols.includes(s)
          return (
            <button
              key={s}
              className={`fc-sym-pill${on ? ' on' : ''}`}
              onClick={() => toggleSymbol(s)}
            >
              {base}
            </button>
          )
        })}
      </div>

      {/* ── grid ── */}
      <main className="fc-grid">
        {loading && signals.length === 0 &&
          Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} />)}

        {!loading && signals.length === 0 && (
          <div className="fc-empty">No signals detected — try a different timeframe or add more symbols</div>
        )}

        {signals.map((sig) => (
          <SignalCard key={sig.id} sig={sig} />
        ))}
      </main>
    </div>
  )
}
