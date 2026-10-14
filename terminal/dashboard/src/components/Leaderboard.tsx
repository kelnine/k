// The leaderboard: every account with its appendix A metrics, sortable and filterable
// in the browser (strategy, instrument, timeframe, free-text search).

import { useMemo, useState, type ReactNode } from 'react'
import type { Account } from '../api/types'
import { fixed, money, params, pct, ratio, rMultiple, tone } from '../lib/format'
import { DEFAULT_SORT, facets, filterAccounts, nextSort, sortAccounts, type Sort, type SortKey } from '../lib/leaderboard'
import { navigate } from '../lib/router'
import { instanceColor } from '../kcharts/trades'
import { Badge, Empty, Select, StateBadge } from './ui'

const COLUMNS: { key: SortKey; label: string; title?: string }[] = [
  { key: 'trades', label: 'Trades', title: 'Closed trades (low n: fewer than 30)' },
  { key: 'win_rate', label: 'Win %' },
  { key: 'profit_factor', label: 'PF', title: 'Profit factor' },
  { key: 'average_r', label: 'Avg R', title: 'Expectancy in R (default ranking)' },
  { key: 'expectancy', label: 'Exp $', title: 'Expectancy per trade in account currency' },
  { key: 'net_pnl', label: 'Net P&L', title: 'Realized, after costs' },
  { key: 'return_pct', label: 'Return', title: '(equity − start) / start' },
  { key: 'max_drawdown_pct', label: 'Max DD', title: 'Largest equity drawdown from a peak' },
  { key: 'open_positions', label: 'Open' },
]

function SortHeader({ column, sort, onSort }: { column: (typeof COLUMNS)[number]; sort: Sort; onSort: (s: Sort) => void }) {
  const on = sort.key === column.key
  return (
    <th className="num sortable" title={column.title} aria-sort={on ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button onClick={() => onSort(nextSort(sort, column.key))}>
        {column.label}
        <span className="sort-mark">{on ? (sort.dir === 'asc' ? '▲' : '▼') : ''}</span>
      </button>
    </th>
  )
}

export function Leaderboard({
  accounts,
  emptyHint,
  showRun = false,
}: {
  accounts: Account[]
  emptyHint?: ReactNode
  showRun?: boolean
}) {
  const [sort, setSort] = useState<Sort>(DEFAULT_SORT)
  const [strategy, setStrategy] = useState('')
  const [instrument, setInstrument] = useState('')
  const [timeframe, setTimeframe] = useState('')
  const [query, setQuery] = useState('')
  const options = useMemo(() => facets(accounts), [accounts])
  const rows = useMemo(
    () => sortAccounts(filterAccounts(accounts, { strategy, instrument, timeframe, query }), sort),
    [accounts, strategy, instrument, timeframe, query, sort],
  )

  if (!accounts.length) return <Empty title="No accounts yet">{emptyHint}</Empty>
  const nameSort = sort.key === 'instance'
  return (
    <div className="leaderboard">
      <div className="filters">
        <label className="field grow">
          <span>Search</span>
          <input type="search" placeholder="strategy, instrument, parameter…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <Select label="Strategy" value={strategy} onChange={setStrategy} options={options.strategies.map((s) => ({ value: s.id, label: s.id }))} />
        <Select label="Instrument" value={instrument} onChange={setInstrument} options={options.instruments.map((i) => ({ value: i, label: i }))} />
        <Select label="Timeframe" value={timeframe} onChange={setTimeframe} options={options.timeframes.map((t) => ({ value: t, label: t }))} />
        <div className="filter-count muted">
          {rows.length} of {accounts.length}
        </div>
      </div>
      <div className="table-wrap">
        <table className="table board">
          <thead>
            <tr>
              <th className="rank">#</th>
              <th className="sticky sortable" aria-sort={nameSort ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                <button onClick={() => setSort(nextSort(sort, 'instance'))}>
                  Strategy<span className="sort-mark">{nameSort ? (sort.dir === 'asc' ? '▲' : '▼') : ''}</span>
                </button>
              </th>
              <th>Setup</th>
              {COLUMNS.map((c) => (
                <SortHeader key={c.key} column={c} sort={sort} onSort={setSort} />
              ))}
              <th>State</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a, i) => {
              const m = a.metrics
              return (
                <tr key={a.id} className="clickable" onClick={() => navigate(`/accounts/${a.id}`)}>
                  <td className="rank muted">{i + 1}</td>
                  <td className="sticky">
                    <div className="who">
                      <span className="swatch" style={{ background: instanceColor(a.instance_id ?? a.id) }} />
                      <div>
                        <div className="strong">{a.instance_id ?? a.name}</div>
                        <div className="muted small">{a.definition_id}{showRun && a.run_name ? ` · ${a.run_name}` : ''}</div>
                      </div>
                    </div>
                  </td>
                  <td className="setup">
                    <div>
                      {a.version?.instruments.join(', ')} · {a.version?.timeframe}
                    </div>
                    <div className="muted small mono" title={params(a.version?.params)}>
                      {params(a.version?.params)}
                    </div>
                  </td>
                  <td className="num">
                    {m.trades}
                    {m.low_sample && <span className="low-n" title="fewer than 30 closed trades">low n</span>}
                  </td>
                  <td className="num">{ratio(m.win_rate)}</td>
                  <td className="num">{m.profit_factor ?? '—'}</td>
                  <td className={`num ${tone(m.average_r)}`}>{rMultiple(m.average_r)}</td>
                  <td className={`num ${tone(m.expectancy)}`}>{money(m.expectancy, { signed: true })}</td>
                  <td className={`num ${tone(m.net_pnl)}`}>{money(m.net_pnl, { signed: true })}</td>
                  <td className={`num ${tone(m.return_pct)}`}>{pct(m.return_pct, { signed: true })}</td>
                  <td className="num down-soft">{m.max_drawdown_pct === null ? '—' : `${fixed(m.max_drawdown_pct)}%`}</td>
                  <td className="num">{m.open_positions || ''}</td>
                  <td>
                    {a.halted ? <Badge tone="bad">halted</Badge> : a.runtime ? <StateBadge state={a.runtime.state} /> : a.kind === 'RUN' ? <Badge>run</Badge> : <Badge>idle</Badge>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {!rows.length && <Empty title="No account matches the filters" />}
    </div>
  )
}
