import { useEffect, useRef, useState } from 'react'
import type { DataAdapter, Timeframe } from '../data'
import { TF_MS } from '../data'
import { ChartEngine, type LegendData } from '../engine/chart'
import type { Drawing, DrawingTool } from '../engine/drawings'
import { formatCompact, formatPrice } from '../engine/utils'

const HISTORY_CHUNK = 500

function drawingsKey(adapterId: string, symbol: string): string {
  return `kcharts:drawings:${adapterId}:${symbol}`
}

function loadDrawings(adapterId: string, symbol: string): Drawing[] {
  try {
    return JSON.parse(localStorage.getItem(drawingsKey(adapterId, symbol)) ?? '[]')
  } catch {
    return []
  }
}

export interface ChartViewProps {
  adapter: DataAdapter
  symbol: string
  tf: Timeframe
  indicators: string[]
  tool: DrawingTool
  active: boolean
  showFrame: boolean
  onActivate(): void
  onToolFinished(): void
}

export function ChartView({
  adapter,
  symbol,
  tf,
  indicators,
  tool,
  active,
  showFrame,
  onActivate,
  onToolFinished,
}: ChartViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const engineRef = useRef<ChartEngine | null>(null)
  const [legend, setLegend] = useState<LegendData | null>(null)
  const [error, setError] = useState<string | null>(null)

  // engine lifecycle
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const engine = new ChartEngine(el, {
      onLegend: setLegend,
      onToolFinished,
      onDrawingsChange: (d) => {
        localStorage.setItem(drawingsKey(adapter.id, symbolRef.current), JSON.stringify(d))
      },
      onLoadMore: () => {
        void loadOlder()
      },
    })
    engineRef.current = engine
    return () => {
      engine.destroy()
      engineRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // refs so stable engine callbacks see current values
  const symbolRef = useRef(symbol)
  symbolRef.current = symbol
  const loadingOlderRef = useRef(false)
  const oldestRef = useRef<number | null>(null)
  const tfRef = useRef(tf)
  tfRef.current = tf

  async function loadOlder(): Promise<void> {
    const engine = engineRef.current
    if (!engine || loadingOlderRef.current || oldestRef.current === null) return
    loadingOlderRef.current = true
    try {
      const older = await adapter.fetchCandles(symbolRef.current, tfRef.current, HISTORY_CHUNK, oldestRef.current)
      if (older.length > 0) oldestRef.current = older[0].time
      engine.prependData(older)
    } catch {
      /* transient fetch error; user can pan again to retry */
      engine.prependData([])
    } finally {
      loadingOlderRef.current = false
    }
  }

  // data load + live subscription per symbol/timeframe
  useEffect(() => {
    const engine = engineRef.current
    if (!engine) return
    let cancelled = false
    let unsub: (() => void) | null = null
    setError(null)

    adapter
      .fetchCandles(symbol, tf, HISTORY_CHUNK)
      .then((candles) => {
        if (cancelled) return
        oldestRef.current = candles[0]?.time ?? null
        engine.setData(candles, TF_MS[tf], symbol)
        engine.setDrawings(loadDrawings(adapter.id, symbol))
        engine.setIndicators(indicators)
        unsub = adapter.subscribeCandles(symbol, tf, (c) => engine.applyUpdate(c))
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message ?? e))
      })

    return () => {
      cancelled = true
      unsub?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adapter, symbol, tf])

  useEffect(() => {
    engineRef.current?.setIndicators(indicators)
  }, [indicators])

  useEffect(() => {
    engineRef.current?.setTool(active ? tool : 'cursor')
  }, [tool, active])

  const c = legend?.candle ?? null
  const prevClose = legend?.prev?.close ?? c?.open ?? 0
  const change = c ? c.close - prevClose : 0
  const changePct = c && prevClose ? (change / prevClose) * 100 : 0
  const up = change >= 0

  return (
    <div
      className={`chart-cell${active && showFrame ? ' active' : ''}`}
      onPointerDownCapture={onActivate}
    >
      <div ref={containerRef} className="chart-canvas" />
      <div className="legend">
        <div className="legend-row">
          <span className="legend-symbol">{symbol}</span>
          <span className="legend-tf">{tf}</span>
          {c && (
            <span className={up ? 'pos' : 'neg'}>
              O {formatPrice(c.open)} H {formatPrice(c.high)} L {formatPrice(c.low)} C {formatPrice(c.close)}{' '}
              {change >= 0 ? '+' : ''}
              {changePct.toFixed(2)}% · Vol {formatCompact(c.volume)}
            </span>
          )}
        </div>
        {legend?.indicators.map((ind) => (
          <div className="legend-row legend-ind" key={ind.name}>
            <span>{ind.name}</span>
            {ind.items.map((it, i) => (
              <span key={i} style={{ color: it.color }}>
                {it.value}
              </span>
            ))}
          </div>
        ))}
      </div>
      {error && <div className="chart-error">Failed to load {symbol}: {error}</div>}
    </div>
  )
}
