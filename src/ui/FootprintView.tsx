import { useEffect, useRef, useState } from 'react'
import type { DataAdapter, Timeframe } from '../data'
import { TF_MS, supportsTrades } from '../data'
import { buildFootprint, chooseRowSize } from '../data/orderflow'
import { FootprintEngine, formatSize, type FootprintLegendData } from '../engine/footprint'
import { formatPrice } from '../engine/utils'

/** Bars requested up front; tick data rarely reaches back further than this. */
const FOOTPRINT_BARS = 60
/** Ceiling on aggTrade rows pulled per load — each page is 1000 prints. */
const TRADE_CAP = 15_000
/** Row count a typical candle should split into at 1x. */
const BASE_ROWS = 14

export interface FootprintViewProps {
  adapter: DataAdapter
  symbol: string
  tf: Timeframe
  rowMul: number
  showPoc: boolean
  active: boolean
  showFrame: boolean
  onActivate(): void
}

export function FootprintView({
  adapter,
  symbol,
  tf,
  rowMul,
  showPoc,
  active,
  showFrame,
  onActivate,
}: FootprintViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const engineRef = useRef<FootprintEngine | null>(null)
  const [legend, setLegend] = useState<FootprintLegendData | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState<string | null>(null)
  const [coverage, setCoverage] = useState<{ built: number; asked: number } | null>(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const engine = new FootprintEngine(el, { onLegend: setLegend })
    engineRef.current = engine
    return () => {
      engine.destroy()
      engineRef.current = null
    }
  }, [])

  useEffect(() => {
    engineRef.current?.setShowPoc(showPoc)
  }, [showPoc])

  useEffect(() => {
    const engine = engineRef.current
    if (!engine) return
    let cancelled = false
    const unsubs: (() => void)[] = []
    setStatus('loading')
    setError(null)
    setCoverage(null)

    if (!supportsTrades(adapter)) {
      setStatus('error')
      setError(`${adapter.name} does not serve tick data, so no footprint can be built.`)
      return
    }

    void (async () => {
      try {
        const tfMs = TF_MS[tf]
        const candles = await adapter.fetchCandles(symbol, tf, FOOTPRINT_BARS)
        if (cancelled) return
        const tick = await adapter.priceTick(symbol).catch(() => null)
        if (cancelled) return
        const rowSize = chooseRowSize(candles, Math.max(2, BASE_ROWS / rowMul), tick)
        const since = candles[0]?.time ?? Date.now() - FOOTPRINT_BARS * tfMs
        const trades = await adapter.fetchRecentTrades(symbol, since, TRADE_CAP)
        if (cancelled) return

        const series = buildFootprint(candles, trades, tfMs, rowSize)
        engine.setSeries(series, tfMs, symbol)
        setCoverage({ built: series.bars.length, asked: candles.length })
        setStatus('ready')

        unsubs.push(adapter.subscribeCandles(symbol, tf, (c) => engine.applyCandle(c)))
        unsubs.push(adapter.subscribeTrades(symbol, (t) => engine.applyTrade(t)))
      } catch (e) {
        if (cancelled) return
        setStatus('error')
        setError(String((e as Error)?.message ?? e))
      }
    })()

    return () => {
      cancelled = true
      for (const u of unsubs) u()
    }
  }, [adapter, symbol, tf, rowMul])

  const bar = legend?.bar ?? null
  const level = legend?.level ?? null
  const delta = bar?.delta ?? 0

  return (
    <div className={`chart-cell${active && showFrame ? ' active' : ''}`} onPointerDownCapture={onActivate}>
      <div ref={containerRef} className="chart-canvas" />
      <div className="legend">
        <div className="legend-row">
          <span className="legend-symbol">{symbol}</span>
          <span className="legend-tf">{tf} · footprint</span>
          {bar && (
            <span className={bar.close >= bar.open ? 'pos' : 'neg'}>
              O {formatPrice(bar.open)} H {formatPrice(bar.high)} L {formatPrice(bar.low)} C{' '}
              {formatPrice(bar.close)}
            </span>
          )}
        </div>
        {bar && (
          <div className="legend-row legend-ind">
            <span>flow</span>
            <span className={delta >= 0 ? 'pos' : 'neg'}>
              Δ {delta >= 0 ? '+' : ''}
              {formatSize(delta)}
            </span>
            <span>cum {legend?.cumDelta === null || legend?.cumDelta === undefined ? '—' : formatSize(legend.cumDelta)}</span>
            <span>vol {formatSize(bar.flowVolume)}</span>
            <span>POC {formatPrice(bar.poc)}</span>
            <span className="legend-dim">row {formatPrice(legend?.rowSize ?? 0)}</span>
          </div>
        )}
        {level && (
          <div className="legend-row legend-ind">
            <span>{formatPrice(level.price)}</span>
            <span className="neg">bid {formatSize(level.bid)}</span>
            <span className="pos">ask {formatSize(level.ask)}</span>
            <span className="legend-dim">imb {(level.imbalance * 100).toFixed(0)}%</span>
          </div>
        )}
      </div>

      <div className="fp-key">
        <span><i className="sw sw-sell" /> sell imbalance</span>
        <span><i className="sw sw-buy" /> buy imbalance</span>
        <span><i className="sw sw-prof" /> volume profile</span>
        {showPoc && <span><i className="sw sw-poc" /> POC</span>}
      </div>

      {status === 'loading' && <div className="chart-note">Building footprint from tick data…</div>}
      {status === 'error' && <div className="chart-error">Footprint unavailable: {error}</div>}
      {status === 'ready' && coverage && coverage.built < coverage.asked && (
        <div className="chart-note dim">
          Tick window covers {coverage.built} of {coverage.asked} bars ({legend?.trades.toLocaleString()} trades)
        </div>
      )}
    </div>
  )
}
