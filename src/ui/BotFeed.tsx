import { useCallback, useEffect, useState } from 'react'
import type { DataAdapter, Timeframe } from '../data/types'
import { detectStructureBreaks } from '../../bot/smc-signals'
import type { StructureBreak } from '../../bot/smc-signals'

// ── types (self-contained, no Node.js imports) ────────────────────────────────

interface Signal {
  id: string
  symbol: string
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
}

function toSignal(symbol: string, sb: StructureBreak, totalBars: number): Signal {
  const { side, level, obTop, obBottom, breakType, breakBar } = sb
  const buf = 0.0005
  const entry = side === 'bull' ? level * (1 + buf) : level * (1 - buf)
  const stop = side === 'bull' ? obBottom * (1 - buf) : obTop * (1 + buf)
  const risk = Math.abs(entry - stop)
  const dir = side === 'bull' ? 1 : -1
  return {
    id: `${symbol}:${side}:${level.toFixed(4)}:${breakBar}`,
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
    barAge: totalBars - 1 - breakBar,
  }
}

async function loadSignals(adapter: DataAdapter, symbol: string, tf: Timeframe): Promise<Signal[]> {
  const candles = await adapter.fetchCandles(symbol, tf, 300)
  const breaks = detectStructureBreaks(candles, 5)
  return breaks
    .slice(-4)
    .map((sb) => toSignal(symbol, sb, candles.length))
    .reverse()
}

// ── price formatter ───────────────────────────────────────────────────────────

function p(n: number): string {
  const d = n >= 1000 ? 2 : n >= 10 ? 3 : n >= 1 ? 4 : 6
  return n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
}

// ── components ────────────────────────────────────────────────────────────────

function SignalCard({ sig }: { sig: Signal }) {
  const base = sig.symbol.replace(/USDT$/, '')
  const bull = sig.side === 'bull'
  const color = bull ? '#26a69a' : '#ef5350'
  const setup = `${sig.breakType} ${bull ? 'Bullish' : 'Bearish'}`
  const risk = Math.abs(sig.entry - sig.stop)

  return (
    <div className="sig-card" style={{ borderLeftColor: color }}>
      <div className="sig-card-head">
        <span className="sig-symbol">${base}</span>
        <span className="sig-setup" style={{ color }}>
          {setup}
        </span>
        <span className={`sig-dir ${sig.side}`}>{bull ? '▲ LONG' : '▼ SHORT'}</span>
      </div>

      <div className="sig-rows">
        <div className="sig-row">
          <span>Entry</span>
          <b>{p(sig.entry)}</b>
        </div>
        <div className="sig-row">
          <span>Stop</span>
          <b style={{ color: '#ef5350' }}>{p(sig.stop)}</b>
        </div>
        <div className="sig-row">
          <span>Risk</span>
          <b>{p(risk)}</b>
        </div>
      </div>

      <div className="sig-targets">
        {(['t1', 't2', 't3'] as const).map((t, i) => {
          const val = t === 't1' ? sig.t1 : t === 't2' ? sig.t2 : sig.t3
          const r = [0.5, 1, 2][i]
          return (
            <div key={t} className="sig-target">
              <span style={{ color }}>{t.toUpperCase()}</span>
              <b>{p(val)}</b>
              <span className="sig-r">{r}R</span>
            </div>
          )
        })}
      </div>

      <div className="sig-footer">
        <span>Level {p(sig.level)}</span>
        <span>{sig.barAge}h ago</span>
      </div>
    </div>
  )
}

// ── main export ───────────────────────────────────────────────────────────────

export function BotFeed({
  adapter,
  symbols,
}: {
  adapter: DataAdapter
  symbols: string[]
}) {
  const [signals, setSignals] = useState<Signal[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(true)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const all: Signal[] = []
      for (const sym of symbols.slice(0, 6)) {
        try {
          const sigs = await loadSignals(adapter, sym, '1h')
          all.push(...sigs)
        } catch {
          /* skip unreachable symbols */
        }
      }
      // sort by recency (barAge ascending)
      all.sort((a, b) => a.barAge - b.barAge)
      setSignals(all.slice(0, 12))
    } finally {
      setLoading(false)
    }
  }, [adapter, symbols])

  useEffect(() => {
    refresh()
  }, [refresh])

  return (
    <div className="bot-feed">
      <div className="bot-feed-header" onClick={() => setOpen((o) => !o)}>
        <span>
          ⚡ Bot Feed
          {signals.length > 0 && !loading && (
            <span className="bot-feed-count">{signals.length}</span>
          )}
        </span>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            className="bot-feed-btn"
            title="Refresh"
            onClick={(e) => {
              e.stopPropagation()
              refresh()
            }}
            disabled={loading}
          >
            {loading ? '…' : '↻'}
          </button>
          <span className="bot-feed-toggle">{open ? '▲' : '▼'}</span>
        </div>
      </div>

      {open && (
        <div className="bot-feed-list">
          {loading && signals.length === 0 && (
            <div className="bot-feed-empty">Scanning markets…</div>
          )}
          {!loading && signals.length === 0 && (
            <div className="bot-feed-empty">No recent signals</div>
          )}
          {signals.map((sig) => (
            <SignalCard key={sig.id} sig={sig} />
          ))}
        </div>
      )}
    </div>
  )
}
