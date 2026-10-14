// One account: who trades it (strategy, parameters, timeframe, instruments), its
// metrics, equity curve, open positions, trades with "explain", signals with reject
// reasons and the instrument chart with its trades.

import { useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { AccountDetail, Equity, Outcome, Page, Position, SignalLogItem, Trade } from '../api/types'
import { EquityCurve } from '../components/EquityCurve'
import { KillSwitchButton } from '../components/KillSwitch'
import { PriceChart } from '../components/PriceChart'
import { PositionsTable, SignalsTable, TradesTable } from '../components/Tables'
import { TradeExplainDrawer } from '../components/TradeExplain'
import { Badge, Card, Empty, ErrorBox, KeyValues, Loading, Pager, Select, Stat, StateBadge, Tabs } from '../components/ui'
import { CHART_TIMEFRAMES, isChartTimeframe, type ChartTimeframe } from '../lib/chartData'
import { ago, dateTime, fixed, money, params, pct, ratio, rMultiple, shortId, tone } from '../lib/format'
import { usePoll } from '../lib/hooks'
import { Link } from '../lib/router'
import { instanceColor } from '../kcharts/trades'

type Tab = 'trades' | 'signals' | 'chart'
const PAGE = 25

function Metrics({ a }: { a: AccountDetail }) {
  const m = a.metrics
  return (
    <div className="stats wide">
      <Stat label="Equity" value={money(m.equity)} sub={m.equity_at ? `marked ${dateTime(m.equity_at)}` : 'not marked yet'} />
      <Stat label="Balance" value={money(m.balance)} sub={`start ${money(m.starting_balance)}`} />
      <Stat label="Return" value={pct(m.return_pct, { signed: true })} tone={tone(m.return_pct)} />
      <Stat label="Net P&L" value={money(m.net_pnl, { signed: true })} tone={tone(m.net_pnl)} sub={`open ${money(m.open_pnl, { signed: true })}`} />
      <Stat label="Trades" value={m.trades} sub={`${m.wins} W · ${m.losses} L${m.scratches ? ` · ${m.scratches} even` : ''}${m.low_sample ? ' · low n' : ''}`} />
      <Stat label="Win rate" value={ratio(m.win_rate)} />
      <Stat label="Profit factor" value={m.profit_factor ?? '—'} title="gross profit / |gross loss|; — when there are no losses" />
      <Stat label="Avg R" value={rMultiple(m.average_r)} tone={tone(m.average_r)} sub={`realized ${rMultiple(m.realized_r)}`} />
      <Stat label="Expectancy" value={money(m.expectancy, { signed: true })} tone={tone(m.expectancy)} sub={`avg win ${money(m.avg_winner)} · loss ${money(m.avg_loser)}`} />
      <Stat label="Max drawdown" value={m.max_drawdown_pct === null ? '—' : `${fixed(m.max_drawdown_pct)}%`} sub={money(m.max_drawdown)} tone={m.max_drawdown_pct && Number(m.max_drawdown_pct) > 0 ? 'down' : ''} />
      <Stat label="Open positions" value={m.open_positions} />
      <Stat label="Last trade" value={m.last_trade_at ? ago(m.last_trade_at) : '—'} sub={dateTime(m.last_trade_at)} />
    </div>
  )
}

export function AccountPage({ id }: { id: string }) {
  const account = usePoll(() => api.get<AccountDetail>(`/accounts/${id}`), [id])
  const equity = usePoll(() => api.get<Equity>(`/accounts/${id}/equity`), [id])
  const positions = usePoll(() => api.get<Position[]>('/positions', { account_id: id, scope: 'all' }), [id])
  const [tab, setTab] = useState<Tab>('trades')
  const [offset, setOffset] = useState(0)
  const [outcome, setOutcome] = useState<Outcome | ''>('')
  const [signalOffset, setSignalOffset] = useState(0)
  const trades = usePoll(() => api.get<Page<Trade>>('/trades', { account_id: id, limit: PAGE, offset }), [id, offset])
  const signals = usePoll(
    () => api.get<Page<SignalLogItem>>('/signals', { account_id: id, outcome, limit: PAGE, offset: signalOffset }),
    [id, outcome, signalOffset],
  )
  const [explain, setExplain] = useState<string | null>(null)
  const [instrument, setInstrument] = useState<string>('')
  const [timeframe, setTimeframe] = useState<ChartTimeframe | ''>('')

  const a = account.data
  if (!a) return <div className="page">{account.error ? <ErrorBox error={account.error} /> : <Loading />}</div>
  const v = a.version
  const chartInstrument = instrument || v?.instruments[0] || ''
  const chartTf: ChartTimeframe = timeframe || (isChartTimeframe(v?.timeframe) ? v!.timeframe as ChartTimeframe : '5m')
  const refresh = () => account.refresh()
  const switchFor = (scope: 'ACCOUNT' | 'STRATEGY') =>
    a.kill_switches.find((s) => s.scope === scope && s.active) !== undefined

  return (
    <div className="page">
      <ErrorBox error={account.error} />
      {a.halted && <div className="banner bad">Trading on this account is halted by a kill switch.</div>}
      <Card>
        <div className="account-head">
          <div className="who big">
            <span className="swatch" style={{ background: instanceColor(a.instance_id ?? a.id) }} />
            <div>
              <h1>{a.instance_id ?? a.name}</h1>
              <div className="muted">
                {a.name} · {a.definition_name}
              </div>
            </div>
          </div>
          <div className="head-badges">
            <Badge tone={a.kind === 'FORWARD' ? 'info' : 'muted'}>{a.kind === 'FORWARD' ? 'forward' : `run · ${a.run_kind?.toLowerCase()}`}</Badge>
            <Badge>{a.mode.toLowerCase()}</Badge>
            <Badge tone={a.status === 'ACTIVE' ? 'ok' : 'warn'}>{a.status.toLowerCase()}</Badge>
            {a.runtime && <StateBadge state={a.runtime.state} title={a.runtime.fault ? String(a.runtime.fault) : undefined} />}
            {a.halted && <Badge tone="bad">halted</Badge>}
          </div>
          {a.kind === 'FORWARD' && (
            <div className="head-actions">
              <KillSwitchButton target={{ scope: 'ACCOUNT', scopeId: a.id, label: a.name }} active={switchFor('ACCOUNT')} onChanged={refresh} compact />
              {a.instance_id && (
                <KillSwitchButton
                  target={{ scope: 'STRATEGY', scopeId: a.instance_id, label: `strategy ${a.instance_id}` }}
                  active={switchFor('STRATEGY')}
                  onChanged={refresh}
                  compact
                />
              )}
            </div>
          )}
        </div>
        {a.runtime?.fault ? <div className="error-box">Fault: {String(a.runtime.fault)}</div> : null}
        <KeyValues
          rows={[
            ['Strategy', `${a.definition_id} v${v?.definition_version ?? '—'}`],
            ['Parameters', <span className="mono">{params(v?.params) || 'defaults'}</span>],
            ['Timeframe', [v?.timeframe, ...(v?.context_timeframes ?? []).map((t) => `${t} context`)].filter(Boolean).join(' · ') || '—'],
            ['Instruments', v?.instruments.map((s) => <Link key={s} to={`/instruments/${encodeURIComponent(s)}`} className="chip">{s}</Link>) ?? '—'],
            ['Version', <span className="mono" title={v?.config_hash}>{shortId(v?.config_hash, 12)}</span>],
            ['Account settings', a.config ? <span className="mono">v{a.config_version}: {params(a.config)}</span> : '—'],
            ...(a.run_id ? ([['Run', <Link to={`/runs/${a.run_id}`}>{a.run_name} · {shortId(a.run_id)}</Link>]] as [string, ReactNode][]) : []),
          ]}
        />
      </Card>

      <Card title="Metrics">
        <Metrics a={a} />
      </Card>

      <Card title="Equity curve">
        {equity.data ? <EquityCurve data={equity.data} /> : equity.error ? <ErrorBox error={equity.error} /> : <Loading />}
      </Card>

      <Card title={`Open positions${positions.data ? ` (${positions.data.length})` : ''}`}>
        {positions.data ? <PositionsTable positions={positions.data} onExplain={setExplain} showAccount={false} /> : <Loading />}
      </Card>

      <Card>
        <Tabs<Tab>
          tabs={[
            { id: 'trades', label: `Trades${trades.data ? ` (${trades.data.total})` : ''}` },
            { id: 'signals', label: `Signals${signals.data ? ` (${signals.data.total})` : ''}` },
            { id: 'chart', label: 'Chart' },
          ]}
          value={tab}
          onChange={setTab}
        />
        {tab === 'trades' &&
          (trades.data ? (
            <>
              <TradesTable trades={trades.data.items} onExplain={setExplain} showAccount={false} />
              <Pager total={trades.data.total} limit={PAGE} offset={offset} onChange={setOffset} />
            </>
          ) : (
            <Loading />
          ))}
        {tab === 'signals' && (
          <>
            <div className="filters">
              <Select
                label="Outcome"
                value={outcome}
                onChange={(value) => {
                  setOutcome(value as Outcome | '')
                  setSignalOffset(0)
                }}
                options={['APPROVED', 'REJECTED', 'INVALID', 'IGNORED', 'NO_DECISION'].map((o) => ({ value: o, label: o.replace('_', ' ').toLowerCase() }))}
              />
            </div>
            {signals.data ? (
              <>
                <SignalsTable signals={signals.data.items} showStrategy={false} />
                <Pager total={signals.data.total} limit={PAGE} offset={signalOffset} onChange={setSignalOffset} />
              </>
            ) : (
              <Loading />
            )}
          </>
        )}
        {tab === 'chart' &&
          (chartInstrument ? (
            <>
              <div className="filters">
                <Select
                  label="Instrument"
                  value={chartInstrument}
                  allLabel={null}
                  onChange={setInstrument}
                  options={(v?.instruments ?? []).map((s) => ({ value: s, label: s }))}
                />
                <Select
                  label="Timeframe"
                  value={chartTf}
                  allLabel={null}
                  onChange={(value) => setTimeframe(value as ChartTimeframe)}
                  options={CHART_TIMEFRAMES.map((t) => ({ value: t, label: t }))}
                />
              </div>
              <PriceChart
                instrument={chartInstrument}
                timeframe={chartTf}
                markers={{ scope: 'all', accountId: a.id }}
                selectedTrade={explain}
                onTradeClick={setExplain}
              />
            </>
          ) : (
            <Empty title="This account has no instrument to chart" />
          ))}
      </Card>
      {explain && <TradeExplainDrawer tradeId={explain} onClose={() => setExplain(null)} />}
    </div>
  )
}
