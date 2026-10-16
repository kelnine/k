// Per instrument: its data feed, which strategies trade it and their open positions.

import { useState } from 'react'
import { api } from '../api/client'
import type { InstrumentDetail, InstrumentSummary } from '../api/types'
import { Leaderboard } from '../components/Leaderboard'
import { PositionsTable } from '../components/Tables'
import { TradeExplainDrawer } from '../components/TradeExplain'
import { Badge, Card, Dot, Empty, ErrorBox, KeyValues, Loading, stateTone } from '../components/ui'
import { ago, dateTime, seconds } from '../lib/format'
import { useNow, usePoll } from '../lib/hooks'
import { Link, navigate } from '../lib/router'

function Feed({ item, now }: { item: InstrumentSummary; now: number }) {
  if (!item.feed) return <span className="muted">no feed reported</span>
  return (
    <span>
      <Dot tone={stateTone(item.feed.state)} /> {item.feed.provider} · {item.feed.state?.toLowerCase() ?? 'unknown'}
      {item.feed.last_bar_open && <span className="muted small"> · bar {ago(item.feed.last_bar_open, now)}</span>}
    </span>
  )
}

export function InstrumentsPage() {
  const now = useNow()
  const list = usePoll(() => api.get<InstrumentSummary[]>('/instruments'), [])
  return (
    <div className="page">
      <ErrorBox error={list.error} />
      {!list.data && !list.error && <Loading />}
      {list.data && !list.data.length && (
        <Empty title="No instruments yet">Instruments appear once strategy instances are registered (kterminal lab provision).</Empty>
      )}
      <div className="grid cards">
        {list.data?.map((item) => (
          <button key={item.symbol} className="card instrument" onClick={() => navigate(`/instruments/${encodeURIComponent(item.symbol)}`)}>
            <div className="instrument-head">
              <strong>{item.symbol}</strong>
              <span className="muted small">{item.name}</span>
              {item.asset_class && <Badge>{item.asset_class.toLowerCase()}</Badge>}
            </div>
            <Feed item={item} now={now} />
            <div className="instrument-stats">
              <span>
                <strong>{item.instances.length}</strong> strategies
              </span>
              <span>
                <strong>{item.open_positions}</strong> open
              </span>
              <span className="muted">{item.timeframes.join(' · ')}</span>
            </div>
            <div className="muted small">last candle {item.last_candle_at ? ago(item.last_candle_at, now) : 'none stored'}</div>
          </button>
        ))}
      </div>
    </div>
  )
}

export function InstrumentPage({ symbol }: { symbol: string }) {
  const now = useNow()
  const detail = usePoll(() => api.get<InstrumentDetail>(`/instruments/${encodeURIComponent(symbol)}`), [symbol])
  const [explain, setExplain] = useState<string | null>(null)
  const d = detail.data
  if (!d) return <div className="page">{detail.error ? <ErrorBox error={detail.error} /> : <Loading />}</div>
  return (
    <div className="page">
      <Card
        title={
          <>
            {d.symbol} <span className="muted small">{d.name}</span>
          </>
        }
        actions={
          <Link to={`/chart?instrument=${encodeURIComponent(d.symbol)}`} className="btn small">
            Open chart
          </Link>
        }
      >
        <KeyValues
          rows={[
            ['Feed', <Feed item={d} now={now} />],
            ['Lag', seconds(d.feed?.lag_seconds)],
            ['Last error', d.feed?.last_error ?? '—'],
            ['Last stored candle', `${dateTime(d.last_candle_at)} (${ago(d.last_candle_at, now)})`],
            ['Timeframes traded', d.timeframes.join(', ') || '—'],
            ['Strategies', d.instances.join(', ') || '—'],
          ]}
        />
      </Card>
      <Card title={`Open positions on ${d.symbol} (${d.positions.length})`}>
        <PositionsTable positions={d.positions} onExplain={setExplain} />
      </Card>
      <Card title={`Forward accounts trading ${d.symbol}`}>
        <Leaderboard accounts={d.accounts} />
      </Card>
      {explain && <TradeExplainDrawer tradeId={explain} onClose={() => setExplain(null)} />}
    </div>
  )
}
