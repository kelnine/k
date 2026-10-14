// Overview: is the forward runtime alive, are the feeds fresh, is anything halted,
// and how is every forward account doing.

import { api } from '../api/client'
import type { Account, FeedStatus, Overview as OverviewData, Page } from '../api/types'
import { KillSwitchButton, KillSwitchList } from '../components/KillSwitch'
import { runtimeLabel, runtimeTone } from '../components/Layout'
import { Leaderboard } from '../components/Leaderboard'
import { Badge, Card, Dot, Empty, ErrorBox, Loading, Stat, stateTone } from '../components/ui'
import { ago, dateTime, money, pct, seconds, shortId, tone } from '../lib/format'
import { totals } from '../lib/leaderboard'
import { useNow, usePoll } from '../lib/hooks'
import { Link } from '../lib/router'

function Runtime({ data, now }: { data: OverviewData; now: number }) {
  const view = data.runtime
  const status = view.status
  if (!view.present)
    return (
      <Empty title="No forward session yet">
        The forward paper runtime has not reported in. Start it on the server; this card turns green once it writes
        its first status.
      </Empty>
    )
  return (
    <div>
      <div className="runtime-head">
        <Dot tone={runtimeTone(view)} />
        <span className="runtime-state">{runtimeLabel(view)}</span>
        {view.stale && <Badge tone="bad">no update for {seconds(view.age_seconds)}</Badge>}
      </div>
      {view.error && <div className="error-box">{view.error}</div>}
      {status && (
        <div className="stats">
          <Stat label="Session" value={status.session_id ?? '—'} sub={status.run_id ? `run ${shortId(status.run_id)}` : undefined} />
          <Stat label="Started" value={dateTime(status.started_at)} sub={ago(status.started_at, now)} />
          <Stat label="Last batch close" value={dateTime(status.last_batch_close)} sub={ago(status.last_batch_close, now)} />
          <Stat label="Updated" value={ago(status.updated_at, now)} sub={`stale after ${seconds(view.stale_after_seconds)}`} />
        </div>
      )}
    </div>
  )
}

function Feeds({ feeds, now }: { feeds: Record<string, FeedStatus>; now: number }) {
  const rows = Object.entries(feeds).sort(([a], [b]) => a.localeCompare(b))
  if (!rows.length) return <Empty title="No data feeds reported" />
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Instrument</th>
            <th>Provider</th>
            <th>State</th>
            <th>Last bar</th>
            <th className="num">Lag</th>
            <th>Last error</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([symbol, feed]) => (
            <tr key={symbol}>
              <td>
                <Link to={`/instruments/${encodeURIComponent(symbol)}`}>{symbol}</Link>
              </td>
              <td>{feed.provider ?? '—'}</td>
              <td>
                <Dot tone={stateTone(feed.state)} /> {feed.state?.toLowerCase() ?? 'unknown'}
              </td>
              <td>
                {dateTime(feed.last_bar_open)} <span className="muted small">{ago(feed.last_bar_open, now)}</span>
              </td>
              <td className="num">{seconds(feed.lag_seconds)}</td>
              <td className="muted small">{feed.last_error ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Overview() {
  const now = useNow()
  const overview = usePoll(() => api.get<OverviewData>('/overview'), [])
  const accounts = usePoll(() => api.get<Page<Account>>('/accounts', { scope: 'forward', limit: 500 }), [])
  const data = overview.data
  const board = accounts.data?.items ?? []
  const sum = totals(board)
  const refresh = () => {
    overview.refresh()
    accounts.refresh()
  }

  return (
    <div className="page">
      <ErrorBox error={overview.error ?? accounts.error} />
      {data?.global_halt && <div className="banner bad">All trading is halted by the global kill switch.</div>}
      {!data && !overview.error && <Loading />}
      {data && (
        <div className="grid three">
          <Card title="Forward runtime">
            <Runtime data={data} now={now} />
          </Card>
          <Card title="Forward accounts">
            <div className="stats">
              <Stat label="Accounts" value={data.forward.accounts} sub={`${data.forward.instances_enabled} instances enabled`} />
              <Stat label="Open positions" value={data.forward.open_positions} />
              <Stat label="Closed trades" value={data.forward.closed_trades} />
              <Stat label="Net P&L" value={money(data.forward.net_pnl, { signed: true })} tone={tone(data.forward.net_pnl)} />
              <Stat
                label="Equity"
                value={money(data.forward.equity, { compact: true })}
                sub={`of ${money(data.forward.starting_balance, { compact: true })} · ${pct(
                  sum.start ? ((sum.equity - sum.start) / sum.start) * 100 : 0,
                  { signed: true },
                )}`}
              />
              <Stat label="Faults (24 h)" value={data.faults_24h} tone={data.faults_24h ? 'down' : ''} />
            </div>
          </Card>
          <Card
            title="Kill switches"
            actions={
              <KillSwitchButton
                target={{ scope: 'GLOBAL', scopeId: '*', label: 'all trading' }}
                active={data.global_halt}
                onChanged={refresh}
              />
            }
          >
            <KillSwitchList switches={data.active_kill_switches} onChanged={refresh} />
            {data.runtime.status?.kill_switch && (
              <p className="muted small">
                Runtime last saw: global {data.runtime.status.kill_switch.global ? 'on' : 'off'}
              </p>
            )}
          </Card>
        </div>
      )}
      {data && (
        <Card title="Data feeds">
          {data.runtime.status ? <Feeds feeds={data.runtime.status.instruments} now={now} /> : <Empty title="No feed status yet" />}
        </Card>
      )}
      <Card
        title="Leaderboard — forward accounts"
        actions={<span className="muted small">{accounts.updatedAt ? `updated ${ago(new Date(accounts.updatedAt).toISOString(), now)}` : ''}</span>}
      >
        {accounts.data ? (
          <Leaderboard
            accounts={board}
            emptyHint={
              <>
                Each strategy instance trades its own Paper 50K account. Create them with <code>kterminal lab provision</code>; lab
                runs are listed under <Link to="/system">System → Runs</Link>.
              </>
            }
          />
        ) : (
          !accounts.error && <Loading />
        )}
      </Card>
    </div>
  )
}
