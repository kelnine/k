import { useCallback, useEffect, useRef, useState } from 'react'
import type { Candle, DataAdapter, Timeframe } from '../data'
import { formatPrice } from '../engine/utils'
import {
  ENTRY_ROLES,
  nearestLevel,
  po3Range,
  rangePosition,
  runModel,
  traderOptions,
  type ModelRun,
  type TraderOptions,
} from '../model'

/**
 * The Frankenstein cockpit: what the ensemble thinks right now, which limb
 * thinks it, what the paper trader did about it, and how that has gone.
 *
 * It runs the same model the chart overlay runs, on the same candles, so the
 * numbers here and the fills on the chart always agree.
 */

const BARS = 500
const RECOMPUTE_MS = 1500

function pct(v: number): string {
  return `${(v * 100).toFixed(0)}%`
}

function money(v: number): string {
  return v.toLocaleString('en-US', { maximumFractionDigits: 0 })
}

function VoteBar({ vote }: { vote: number }) {
  const w = Math.min(50, Math.abs(vote) * 50)
  const bull = vote >= 0
  return (
    <span className="vote-bar">
      <span className="vote-axis" />
      <span
        className={`vote-fill ${bull ? 'bull' : 'bear'}`}
        style={{ width: `${w}%`, left: bull ? '50%' : `${50 - w}%` }}
      />
    </span>
  )
}

function Equity({ run }: { run: ModelRun }) {
  const pts = run.equity
  if (pts.length < 2) return null
  const vals = pts.map((p) => p.equity)
  const lo = Math.min(...vals, run.startEquity)
  const hi = Math.max(...vals, run.startEquity)
  const span = hi - lo || 1
  const step = 100 / (pts.length - 1)
  const d = vals.map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(2)},${(30 - ((v - lo) / span) * 30).toFixed(2)}`).join(' ')
  const base = (30 - ((run.startEquity - lo) / span) * 30).toFixed(2)
  const up = vals[vals.length - 1] >= run.startEquity
  return (
    <svg className="equity-spark" viewBox="0 0 100 30" preserveAspectRatio="none">
      <line x1="0" y1={base} x2="100" y2={base} stroke="rgba(255,255,255,0.18)" strokeWidth="0.5" strokeDasharray="2 2" />
      <path d={d} fill="none" stroke={up ? 'var(--up)' : 'var(--down)'} strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

/** The PO3 dealing range read-out: where price sits and what it is nearest. */
function GoldbachStrip({ run, price }: { run: ModelRun; price: number }) {
  const range = po3Range(price, run.po3)
  const pos = Math.max(0, Math.min(1, rangePosition(price, range)))
  const level = nearestLevel(price, range, { roles: ENTRY_ROLES })
  const premium = pos > 0.5
  return (
    <div className="po3">
      <div className="po3-head">
        <span>PO3 {run.po3} · {run.po3 * 3}</span>
        <b className={premium ? 'neg' : 'pos'}>
          {(pos * 100).toFixed(0)}% {premium ? 'premium' : 'discount'}
        </b>
      </div>
      <div className="po3-bar">
        <span className="po3-eq" />
        <span className="po3-mark" style={{ bottom: `${pos * 100}%` }} />
      </div>
      <div className="po3-foot">
        <span>{formatPrice(range.low)}</span>
        <span>{level ? `${level.label.split(' | ')[0]} ${level.role} @ ${formatPrice(level.price)}` : '—'}</span>
        <span>{formatPrice(range.high)}</span>
      </div>
    </div>
  )
}

export function ModelPanel({
  adapter,
  symbol,
  tf,
  entryStyle,
  onEntryStyle,
}: {
  adapter: DataAdapter
  symbol: string
  tf: Timeframe
  entryStyle: TraderOptions['entryStyle']
  onEntryStyle(style: TraderOptions['entryStyle']): void
}) {
  const [run, setRun] = useState<ModelRun | null>(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const candlesRef = useRef<Candle[]>([])
  const lastRunRef = useRef(0)

  const recompute = useCallback(
    (force = false) => {
      const candles = candlesRef.current
      if (candles.length < 60) return
      const now = Date.now()
      if (!force && now - lastRunRef.current < RECOMPUTE_MS) return
      lastRunRef.current = now
      setRun(runModel(candles, symbol, { trader: traderOptions() }))
    },
    // entryStyle is read through the shared setting, but a change must re-run
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [symbol, entryStyle],
  )

  useEffect(() => {
    let cancelled = false
    let unsub: (() => void) | null = null
    setLoading(true)
    setError(null)
    setRun(null)

    adapter
      .fetchCandles(symbol, tf, BARS)
      .then((candles) => {
        if (cancelled) return
        candlesRef.current = candles
        recompute(true)
        setLoading(false)
        unsub = adapter.subscribeCandles(symbol, tf, (c) => {
          const arr = candlesRef.current
          const last = arr[arr.length - 1]
          if (!last) return
          if (c.time === last.time) arr[arr.length - 1] = c
          else if (c.time > last.time) arr.push(c)
          recompute()
        })
      })
      .catch((e) => {
        if (cancelled) return
        setError(String(e?.message ?? e))
        setLoading(false)
      })

    return () => {
      cancelled = true
      unsub?.()
    }
  }, [adapter, symbol, tf, recompute])

  const last = run?.bars[run.bars.length - 1]
  const dir = !last ? 'flat' : last.gated >= 0.34 ? 'long' : last.gated <= -0.34 ? 'short' : 'flat'
  const pos = run?.open ?? null
  const price = candlesRef.current[candlesRef.current.length - 1]?.close ?? 0
  const openR = pos ? ((price - pos.entry) * (pos.side === 'bull' ? 1 : -1)) / pos.risk : 0

  return (
    <div className="model-panel">
      <div className="model-header" onClick={() => setOpen((o) => !o)}>
        <span>
          🧠 Frankenstein AI
          <span className="model-paper" title="Simulated fills — no broker is connected">
            paper
          </span>
        </span>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            className="bot-feed-btn"
            title="Re-run the model"
            onClick={(e) => {
              e.stopPropagation()
              recompute(true)
            }}
          >
            ↻
          </button>
          <span className="bot-feed-toggle">{open ? '▲' : '▼'}</span>
        </div>
      </div>

      {open && (
        <div className="model-body">
          {loading && <div className="bot-feed-empty">Running the model…</div>}
          {error && <div className="bot-feed-empty">Model offline: {error}</div>}
          {run && last && (
            <>
              <div className={`model-verdict ${dir}`}>
                <div className="verdict-dir">
                  {dir === 'long' ? '▲ LONG' : dir === 'short' ? '▼ SHORT' : '— FLAT'}
                </div>
                <div className="verdict-score">
                  {last.gated >= 0 ? '+' : ''}
                  {last.gated.toFixed(2)}
                  <span className="verdict-sub">
                    raw {last.score.toFixed(2)} · gate {pct(last.gate)}
                  </span>
                </div>
              </div>

              <GoldbachStrip run={run} price={price} />

              {run.pending && (
                <div className={`model-order ${run.pending.side}`}>
                  <span className="order-tag">
                    {run.pending.qty} | {run.pending.side === 'bull' ? 'Buy' : 'Sell'} Limit
                  </span>
                  <span className="order-level">{run.pending.level}</span>
                  <b>{formatPrice(run.pending.price)}</b>
                </div>
              )}

              <div className="model-section">{symbol} · {tf} · {run.votes.length} limbs</div>
              <div className="limbs">
                {run.votes.map((v) => (
                  <div className="limb" key={v.id} title={`weight ${v.weight}`}>
                    <span className="limb-name">{v.name}</span>
                    <VoteBar vote={v.vote} />
                    <span className={`limb-vote ${v.vote > 0.01 ? 'pos' : v.vote < -0.01 ? 'neg' : ''}`}>
                      {v.vote >= 0 ? '+' : ''}
                      {v.vote.toFixed(2)}
                    </span>
                    <span className="limb-note">{v.note}</span>
                  </div>
                ))}
              </div>

              {pos && (
                <div className={`model-position ${pos.side}`}>
                  <div className="pos-head">
                    <b>{pos.side === 'bull' ? 'LONG' : 'SHORT'} {pos.qty}</b>
                    <span className={openR >= 0 ? 'pos-r pos' : 'pos-r neg'}>
                      {openR >= 0 ? '+' : ''}
                      {openR.toFixed(2)}R
                    </span>
                  </div>
                  <div className="pos-rows">
                    <span>Entry</span>
                    <b>{formatPrice(pos.entry)}</b>
                    <span>Stop</span>
                    <b className="neg">{formatPrice(pos.stop)}</b>
                    {pos.targets.map((t, i) => (
                      <span key={i} style={{ display: 'contents' }}>
                        <span>T{i + 1}</span>
                        <b className="pos">{formatPrice(t)}</b>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div className="model-section">Paper performance · {BARS} bars</div>
              <Equity run={run} />
              <div className="model-stats">
                <div>
                  <span>Return</span>
                  <b className={run.stats.returnPct >= 0 ? 'pos' : 'neg'}>
                    {run.stats.returnPct >= 0 ? '+' : ''}
                    {run.stats.returnPct.toFixed(1)}%
                  </b>
                </div>
                <div>
                  <span>Equity</span>
                  <b>${money(run.equity[run.equity.length - 1]?.equity ?? run.startEquity)}</b>
                </div>
                <div>
                  <span>Trades</span>
                  <b>{run.stats.trades}</b>
                </div>
                <div>
                  <span>Win rate</span>
                  <b>{pct(run.stats.winRate)}</b>
                </div>
                <div>
                  <span>Expectancy</span>
                  <b className={run.stats.expectancyR >= 0 ? 'pos' : 'neg'}>
                    {run.stats.expectancyR >= 0 ? '+' : ''}
                    {run.stats.expectancyR.toFixed(2)}R
                  </b>
                </div>
                <div>
                  <span>Profit factor</span>
                  <b>{isFinite(run.stats.profitFactor) ? run.stats.profitFactor.toFixed(2) : '∞'}</b>
                </div>
                <div>
                  <span>Max DD</span>
                  <b className="neg">{pct(run.stats.maxDrawdown)}</b>
                </div>
                <div>
                  <span>Total</span>
                  <b className={run.stats.totalR >= 0 ? 'pos' : 'neg'}>
                    {run.stats.totalR >= 0 ? '+' : ''}
                    {run.stats.totalR.toFixed(1)}R
                  </b>
                </div>
              </div>

              <div className="model-section">Entries</div>
              <div className="entry-toggle">
                {(['goldbach', 'market'] as const).map((style) => (
                  <button
                    key={style}
                    className={entryStyle === style ? 'on' : ''}
                    title={
                      style === 'goldbach'
                        ? 'Rest a limit on the nearest Goldbach level price has to come back for'
                        : 'Take the next bar’s open'
                    }
                    onClick={() => onEntryStyle(style)}
                  >
                    {style === 'goldbach' ? 'Goldbach limit' : 'Market'}
                  </button>
                ))}
              </div>

              <div className="model-section">Recent fills</div>
              <div className="model-trades">
                {run.closed.length === 0 && <div className="bot-feed-empty">No closed trades yet</div>}
                {run.closed
                  .slice(-8)
                  .reverse()
                  .map((t) => (
                    <div className="trade-row" key={t.id}>
                      <span className={`trade-side ${t.side}`}>{t.side === 'bull' ? '▲' : '▼'}</span>
                      <span className="trade-px">{formatPrice(t.entry)}</span>
                      <span className="trade-arrow">→</span>
                      <span className="trade-px">{formatPrice(t.exitPrice)}</span>
                      <span className="trade-reason">{t.level ? t.level.split(' | ')[0] : t.reason}</span>
                      <span className={t.r >= 0 ? 'trade-r pos' : 'trade-r neg'}>
                        {t.r >= 0 ? '+' : ''}
                        {t.r.toFixed(2)}R
                      </span>
                    </div>
                  ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
