import { useState } from 'react'
import { api } from '../api/client'
import type { Instance, InstrumentSummary, Outcome, Page, SignalLogItem, Trade } from '../api/types'
import { SignalsTable, TradesTable } from '../components/Tables'
import { TradeExplainDrawer } from '../components/TradeExplain'
import { Card, ErrorBox, Loading, Pager, Select } from '../components/ui'
import { usePoll } from '../lib/hooks'
import { setQuery, useLocation } from '../lib/router'

const PAGE = 50

const SCOPES = [
  { value: 'forward', label: 'Forward accounts' },
  { value: 'run', label: 'Lab / backtest runs' },
]

/** Filter choices shared by the Trades and Signals pages. */
function useChoices() {
  const instances = usePoll(() => api.get<Instance[]>('/instances'), [], 60_000)
  const instruments = usePoll(() => api.get<InstrumentSummary[]>('/instruments'), [], 60_000)
  return {
    instances: (instances.data ?? []).map((i) => ({ value: i.id, label: i.id })),
    instruments: (instruments.data ?? []).map((i) => ({ value: i.symbol, label: i.symbol })),
  }
}

export function TradesPage() {
  const { query } = useLocation()
  const scope = query.get('scope') ?? 'forward'
  const status = query.get('status') ?? ''
  const instance = query.get('instance') ?? ''
  const instrument = query.get('instrument') ?? ''
  const direction = query.get('direction') ?? ''
  const runId = query.get('run_id') ?? ''
  const offset = Number(query.get('offset') ?? 0) || 0
  const choices = useChoices()
  const [explain, setExplain] = useState<string | null>(null)
  const trades = usePoll(
    () =>
      api.get<Page<Trade>>('/trades', {
        scope: runId ? 'all' : scope,
        status,
        instance_id: instance,
        instrument,
        direction,
        run_id: runId,
        limit: PAGE,
        offset,
      }),
    [scope, status, instance, instrument, direction, runId, offset],
  )
  const set = (key: string) => (value: string) => setQuery({ [key]: value, offset: null })

  return (
    <div className="page">
      <Card title="Trades">
        <div className="filters">
          <Select label="Accounts" value={scope} onChange={set('scope')} options={SCOPES} allLabel="All" />
          <Select label="Status" value={status} onChange={set('status')} options={[{ value: 'OPEN', label: 'Open' }, { value: 'CLOSED', label: 'Closed' }]} />
          <Select label="Strategy" value={instance} onChange={set('instance')} options={choices.instances} />
          <Select label="Instrument" value={instrument} onChange={set('instrument')} options={choices.instruments} />
          <Select label="Side" value={direction} onChange={set('direction')} options={[{ value: 'LONG', label: 'Long' }, { value: 'SHORT', label: 'Short' }]} />
          {runId && (
            <button className="btn small" onClick={() => setQuery({ run_id: null, offset: null })}>
              run {runId.slice(0, 8)} ✕
            </button>
          )}
        </div>
        <ErrorBox error={trades.error} />
        {trades.data ? (
          <>
            <TradesTable trades={trades.data.items} onExplain={setExplain} />
            <Pager total={trades.data.total} limit={PAGE} offset={offset} onChange={(o) => setQuery({ offset: String(o) })} />
          </>
        ) : (
          !trades.error && <Loading />
        )}
      </Card>
      {explain && <TradeExplainDrawer tradeId={explain} onClose={() => setExplain(null)} />}
    </div>
  )
}

export function SignalsPage() {
  const { query } = useLocation()
  const scope = query.get('scope') ?? 'forward'
  const outcome = (query.get('outcome') ?? '') as Outcome | ''
  const instance = query.get('instance') ?? ''
  const instrument = query.get('instrument') ?? ''
  const action = query.get('action') ?? ''
  const offset = Number(query.get('offset') ?? 0) || 0
  const choices = useChoices()
  const signals = usePoll(
    () =>
      api.get<Page<SignalLogItem>>('/signals', {
        scope,
        outcome,
        instance_id: instance,
        instrument,
        action,
        limit: PAGE,
        offset,
      }),
    [scope, outcome, instance, instrument, action, offset],
  )
  const set = (key: string) => (value: string) => setQuery({ [key]: value, offset: null })
  return (
    <div className="page">
      <Card title="Signals">
        <p className="muted small">
          Every signal the strategies produced and what became of it: approved or rejected by the risk layer (with the
          first failing rule), refused by the framework as invalid, or recorded without routing.
        </p>
        <div className="filters">
          <Select label="Accounts" value={scope} onChange={set('scope')} options={SCOPES} allLabel="All" />
          <Select
            label="Outcome"
            value={outcome}
            onChange={set('outcome')}
            options={['APPROVED', 'REJECTED', 'INVALID', 'IGNORED', 'NO_DECISION'].map((o) => ({ value: o, label: o.replace('_', ' ').toLowerCase() }))}
          />
          <Select label="Strategy" value={instance} onChange={set('instance')} options={choices.instances} />
          <Select label="Instrument" value={instrument} onChange={set('instrument')} options={choices.instruments} />
          <Select
            label="Action"
            value={action}
            onChange={set('action')}
            options={['LONG', 'SHORT', 'EXIT_LONG', 'EXIT_SHORT', 'MOVE_SL', 'NO_TRADE'].map((a) => ({ value: a, label: a.replace('_', ' ').toLowerCase() }))}
          />
        </div>
        <ErrorBox error={signals.error} />
        {signals.data ? (
          <>
            <SignalsTable signals={signals.data.items} />
            <Pager total={signals.data.total} limit={PAGE} offset={offset} onChange={(o) => setQuery({ offset: String(o) })} />
          </>
        ) : (
          !signals.error && <Loading />
        )}
      </Card>
    </div>
  )
}
