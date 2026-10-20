// Candles from the API drawn with the KCharts engine, with every strategy's trades on
// top. Refreshes every 10 s without losing the user's zoom; panning to the left edge
// loads older bars.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Params } from '../api/client'
import type { Candles, TradeMarker } from '../api/types'
import { ChartEngine, type LegendData } from '../kcharts/chart'
import type { Candle } from '../kcharts/types'
import { formatPrice } from '../kcharts/utils'
import { POLL_MS } from '../lib/hooks'
import { TIMEFRAME_MS, toCandles, toChartTrades, type ChartTimeframe } from '../lib/chartData'
import { Empty, ErrorBox } from './ui'

export interface MarkerQuery {
  scope: 'forward' | 'run' | 'all' | 'none'
  accountId?: string
  runId?: string
  instances?: string[]
}

const PAGE = 1000

export function PriceChart({
  instrument,
  timeframe,
  markers,
  indicators = [],
  selectedTrade = null,
  onTradeClick,
  onMarkers,
  height = 460,
}: {
  instrument: string
  timeframe: ChartTimeframe
  markers: MarkerQuery
  indicators?: string[]
  selectedTrade?: string | null
  onTradeClick?: (id: string) => void
  onMarkers?: (markers: TradeMarker[]) => void
  height?: number
}) {
  const box = useRef<HTMLDivElement>(null)
  const engine = useRef<ChartEngine | null>(null)
  const candles = useRef<Candle[]>([])
  const trades = useRef<Map<string, TradeMarker>>(new Map())
  const loadingOlder = useRef(false)
  const [legend, setLegend] = useState<LegendData | null>(null)
  const [meta, setMeta] = useState<Pick<Candles, 'source' | 'built_from'> | null>(null)
  const [empty, setEmpty] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const clickRef = useRef(onTradeClick)
  clickRef.current = onTradeClick
  const markersRef = useRef(onMarkers)
  markersRef.current = onMarkers

  const params = useCallback(
    (extra: Params = {}): Params => ({
      instrument,
      timeframe,
      limit: PAGE,
      markers: markers.scope,
      account_id: markers.accountId,
      run_id: markers.runId,
      instance: markers.instances && markers.instances.length ? markers.instances : undefined,
      ...extra,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [instrument, timeframe, markers.scope, markers.accountId, markers.runId, (markers.instances ?? []).join(',')],
  )

  const publishTrades = useCallback(() => {
    const list = [...trades.current.values()]
    engine.current?.setTrades(toChartTrades(list))
    markersRef.current?.(list)
  }, [])

  const mergeMarkers = useCallback(
    (found: TradeMarker[]) => {
      for (const m of found) trades.current.set(m.trade_id, m)
      publishTrades()
    },
    [publishTrades],
  )

  const loadOlder = useCallback(async () => {
    const first = candles.current[0]
    if (!first || loadingOlder.current) return
    loadingOlder.current = true
    try {
      const page = await api.get<Candles>('/candles', params({ until: new Date(first.time).toISOString() }))
      const older = toCandles(page.candles)
      candles.current = [...older.filter((c) => c.time < first.time), ...candles.current]
      engine.current?.prependData(older)
      mergeMarkers(page.markers)
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)))
    } finally {
      loadingOlder.current = false
    }
  }, [params, mergeMarkers])

  // engine lifecycle
  useEffect(() => {
    if (!box.current) return
    const chart = new ChartEngine(box.current, {
      onLegend: setLegend,
      onTradeClick: (id) => clickRef.current?.(id),
      onLoadMore: () => void loadOlderRef.current(),
    })
    engine.current = chart
    return () => {
      chart.destroy()
      engine.current = null
    }
  }, [])
  const loadOlderRef = useRef(loadOlder)
  loadOlderRef.current = loadOlder

  useEffect(() => {
    engine.current?.setIndicators(indicators)
  }, [indicators])

  useEffect(() => {
    engine.current?.selectTrade(selectedTrade)
  }, [selectedTrade])

  // first load, and a fresh load whenever the instrument, timeframe or filter changes
  useEffect(() => {
    let cancelled = false
    trades.current = new Map()
    candles.current = []
    setError(null)
    api
      .get<Candles>('/candles', params())
      .then((page) => {
        if (cancelled) return
        candles.current = toCandles(page.candles)
        setEmpty(candles.current.length === 0)
        setMeta({ source: page.source, built_from: page.built_from })
        engine.current?.setData(candles.current, TIMEFRAME_MS[timeframe], instrument)
        mergeMarkers(page.markers)
      })
      .catch((err: unknown) => !cancelled && setError(err instanceof Error ? err : new Error(String(err))))
    return () => {
      cancelled = true
    }
  }, [params, instrument, timeframe, mergeMarkers])

  // live refresh: newest bars and trades, keeping the user's view
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.hidden || !candles.current.length) return
      api
        .get<Candles>('/candles', params({ limit: 50 }))
        .then((page) => {
          const fresh = toCandles(page.candles)
          const last = candles.current[candles.current.length - 1]
          for (const c of fresh) {
            if (c.time < last.time) continue
            engine.current?.applyUpdate(c)
            if (c.time === last.time) candles.current[candles.current.length - 1] = c
            else candles.current.push(c)
          }
          mergeMarkers(page.markers)
        })
        .catch(() => undefined) // the next tick retries; the page shows API errors elsewhere
    }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [params, mergeMarkers])

  const c = legend?.candle
  return (
    <div className="price-chart">
      <div className="chart-legend">
        <strong>{instrument}</strong> <span className="muted">{timeframe}</span>
        {c && (
          <span className={`ohlc ${c.close >= c.open ? 'up' : 'down'}`}>
            O {formatPrice(c.open)} H {formatPrice(c.high)} L {formatPrice(c.low)} C {formatPrice(c.close)}
          </span>
        )}
        {meta?.source && (
          <span className="muted small">
            {meta.source}
            {meta.built_from ? ` · built from ${meta.built_from}` : ''}
          </span>
        )}
      </div>
      <ErrorBox error={error} />
      <div className="chart-box" ref={box} style={{ height }}>
        {empty && (
          <div className="chart-empty">
            <Empty title={`No ${instrument} candles stored yet`}>
              The forward runtime stores the bars it trades on; they appear here once it runs.
            </Empty>
          </div>
        )}
      </div>
    </div>
  )
}
