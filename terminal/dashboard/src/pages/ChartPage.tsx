// Pick an instrument and timeframe: candles from the candles table, with every
// strategy's trades on it. Strategies can be hidden; clicking a marker explains the trade.

import { useMemo, useState } from 'react'
import { api } from '../api/client'
import type { InstrumentSummary, TradeMarker } from '../api/types'
import { PriceChart } from '../components/PriceChart'
import { TradeExplainDrawer } from '../components/TradeExplain'
import { Card, Empty, ErrorBox, Loading, Select } from '../components/ui'
import { CHART_TIMEFRAMES, isChartTimeframe, type ChartTimeframe } from '../lib/chartData'
import { usePoll } from '../lib/hooks'
import { setQuery, useLocation } from '../lib/router'
import { instanceColor } from '../kcharts/trades'

// KCharts indicator ids (src/kcharts/indicators). Display only: strategies compute
// their own indicators in the backend (Pine-parity library, docs/14).
const INDICATORS = [
  { id: 'ema21', label: 'EMA 21' },
  { id: 'ma50', label: 'MA 50' },
  { id: 'ma200', label: 'MA 200' },
  { id: 'vwap', label: 'VWAP' },
  { id: 'bb', label: 'BB' },
  { id: 'rsi', label: 'RSI' },
]

export function ChartPage() {
  const { query } = useLocation()
  const instruments = usePoll(() => api.get<InstrumentSummary[]>('/instruments'), [], 60_000)
  const list = instruments.data ?? []
  const symbol = query.get('instrument') ?? list[0]?.symbol ?? ''
  const tfParam = query.get('tf')
  const item = list.find((i) => i.symbol === symbol)
  const timeframe: ChartTimeframe = isChartTimeframe(tfParam)
    ? tfParam
    : isChartTimeframe(item?.timeframes[0])
      ? (item!.timeframes[0] as ChartTimeframe)
      : '5m'
  const scope = (query.get('scope') ?? 'forward') as 'forward' | 'run' | 'all'
  const hidden = useMemo(() => new Set((query.get('hide') ?? '').split(',').filter(Boolean)), [query])
  const [indicators, setIndicators] = useState<string[]>([])
  const [explain, setExplain] = useState<string | null>(null)
  const [markers, setMarkers] = useState<TradeMarker[]>([])

  const strategies = useMemo(() => {
    const ids = new Set<string>(item?.instances ?? [])
    for (const m of markers) ids.add(m.instance_id)
    return [...ids].sort()
  }, [item, markers])
  const shown = strategies.filter((s) => !hidden.has(s))
  const toggle = (id: string) => {
    const next = new Set(hidden)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setQuery({ hide: [...next].join(',') || null })
  }
  const counts = useMemo(() => {
    const out = new Map<string, number>()
    for (const m of markers) out.set(m.instance_id, (out.get(m.instance_id) ?? 0) + 1)
    return out
  }, [markers])

  return (
    <div className="page">
      <ErrorBox error={instruments.error} />
      {!instruments.data && !instruments.error && <Loading />}
      {instruments.data && !list.length && <Empty title="No instruments to chart yet" />}
      {symbol && (
        <Card>
          <div className="filters">
            <Select
              label="Instrument"
              value={symbol}
              allLabel={null}
              onChange={(value) => setQuery({ instrument: value, hide: null })}
              options={list.map((i) => ({ value: i.symbol, label: i.symbol }))}
            />
            <div className="field">
              <span>Timeframe</span>
              <div className="seg">
                {CHART_TIMEFRAMES.map((tf) => (
                  <button key={tf} className={`seg-btn ${tf === timeframe ? 'on' : ''}`} onClick={() => setQuery({ tf })}>
                    {tf}
                  </button>
                ))}
              </div>
            </div>
            <Select
              label="Trades of"
              value={scope}
              allLabel={null}
              onChange={(value) => setQuery({ scope: value })}
              options={[
                { value: 'forward', label: 'Forward accounts' },
                { value: 'run', label: 'Lab runs' },
                { value: 'all', label: 'All accounts' },
              ]}
            />
            <div className="field">
              <span>Indicators</span>
              <div className="seg">
                {INDICATORS.map((ind) => (
                  <button
                    key={ind.id}
                    className={`seg-btn ${indicators.includes(ind.id) ? 'on' : ''}`}
                    onClick={() => setIndicators((cur) => (cur.includes(ind.id) ? cur.filter((x) => x !== ind.id) : [...cur, ind.id]))}
                  >
                    {ind.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
          {strategies.length > 0 && (
            <div className="legend-chips">
              {strategies.map((id) => (
                <button key={id} className={`chip toggle ${hidden.has(id) ? 'off' : ''}`} onClick={() => toggle(id)} title={hidden.has(id) ? 'show' : 'hide'}>
                  <span className="swatch" style={{ background: instanceColor(id) }} />
                  {id}
                  <span className="muted small">{counts.get(id) ?? 0}</span>
                </button>
              ))}
            </div>
          )}
          <PriceChart
            instrument={symbol}
            timeframe={timeframe}
            markers={{ scope, instances: hidden.size ? shown : undefined }}
            indicators={indicators}
            selectedTrade={explain}
            onTradeClick={setExplain}
            onMarkers={setMarkers}
            height={520}
          />
          <p className="muted small">
            ▲ long entry · ▼ short entry · ● exit (green win, red loss) · dashed lines: stop (red) and target (green) of open
            or selected trades. Drag to pan, wheel to zoom, double-click to reset; click a marker to explain the trade.
          </p>
        </Card>
      )}
      {explain && <TradeExplainDrawer tradeId={explain} onClose={() => setExplain(null)} />}
    </div>
  )
}
