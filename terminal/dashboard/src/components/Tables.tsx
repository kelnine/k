import type { Position, SignalLogItem, Trade } from '../api/types'
import { ago, between, dateTime, decimal, label, money, qty, rMultiple, tone } from '../lib/format'
import { Link } from '../lib/router'
import { instanceColor } from '../kcharts/trades'
import { Badge, Empty, type Tone } from './ui'

function Who({ instance, account, accountId }: { instance: string; account?: string; accountId?: string }) {
  return (
    <div className="who">
      <span className="swatch" style={{ background: instanceColor(instance) }} />
      <div>
        <div>{instance}</div>
        {account && accountId && (
          <Link to={`/accounts/${accountId}`} className="muted small">
            {account}
          </Link>
        )}
      </div>
    </div>
  )
}

function Side({ direction }: { direction: string }) {
  return <span className={`side ${direction === 'LONG' ? 'up' : 'down'}`}>{direction === 'LONG' ? 'Long' : 'Short'}</span>
}

export function TradesTable({
  trades,
  onExplain,
  showAccount = true,
}: {
  trades: Trade[]
  onExplain: (id: string) => void
  showAccount?: boolean
}) {
  if (!trades.length) return <Empty title="No trades yet" />
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {showAccount && <th>Strategy</th>}
            <th>Instrument</th>
            <th>Side</th>
            <th className="num">Qty</th>
            <th>Entry</th>
            <th>Exit</th>
            <th>Reason</th>
            <th className="num">Held</th>
            <th className="num">Net P&amp;L</th>
            <th className="num">R</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr key={t.id} className="clickable" onClick={() => onExplain(t.id)}>
              {showAccount && (
                <td>
                  <Who instance={t.instance_id} account={t.account_name} accountId={t.account_id} />
                </td>
              )}
              <td>
                {t.instrument} <span className="muted small">{t.timeframe}</span>
              </td>
              <td>
                <Side direction={t.direction} />
              </td>
              <td className="num">{qty(t.qty)}</td>
              <td>
                <div className="num-inline">{decimal(t.entry_price)}</div>
                <div className="muted small">{dateTime(t.entry_time)}</div>
              </td>
              <td>
                {t.status === 'OPEN' ? (
                  <Badge tone="info">open</Badge>
                ) : (
                  <>
                    <div className="num-inline">{decimal(t.exit_price)}</div>
                    <div className="muted small">{dateTime(t.exit_time)}</div>
                  </>
                )}
              </td>
              <td>{t.exit_reason ? label(t.exit_reason) : '—'}</td>
              <td className="num">{between(t.entry_time, t.exit_time)}</td>
              <td className={`num ${tone(t.net_pnl)}`}>{money(t.net_pnl, { signed: true })}</td>
              <td className={`num ${tone(t.r_multiple)}`}>{rMultiple(t.r_multiple)}</td>
              <td>
                <button className="btn small ghost" onClick={(e) => (e.stopPropagation(), onExplain(t.id))}>
                  Explain
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function PositionsTable({
  positions,
  onExplain,
  showAccount = true,
}: {
  positions: Position[]
  onExplain: (id: string) => void
  showAccount?: boolean
}) {
  if (!positions.length) return <Empty title="No open positions" />
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {showAccount && <th>Strategy</th>}
            <th>Instrument</th>
            <th>Side</th>
            <th className="num">Qty</th>
            <th className="num">Entry</th>
            <th className="num">Stop</th>
            <th className="num">Target</th>
            <th className="num">Last</th>
            <th className="num">Open P&amp;L</th>
            <th className="num">R</th>
            <th>Opened</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr key={p.id} className="clickable" onClick={() => onExplain(p.id)}>
              {showAccount && (
                <td>
                  <Who instance={p.instance_id} account={p.account_name} accountId={p.account_id} />
                </td>
              )}
              <td>{p.instrument}</td>
              <td>
                <Side direction={p.direction} />
              </td>
              <td className="num">{qty(p.qty)}</td>
              <td className="num">{decimal(p.entry_price)}</td>
              <td className="num down-soft">{decimal(p.current_stop ?? p.initial_stop)}</td>
              <td className="num up-soft">{decimal(p.current_target ?? p.initial_target)}</td>
              <td className="num" title={p.last_price_at ? `close of the bar ending ${dateTime(p.last_price_at)}` : 'no candle stored'}>
                {decimal(p.last_price)}
              </td>
              <td className={`num ${tone(p.unrealized_pnl)}`}>{money(p.unrealized_pnl, { signed: true })}</td>
              <td className={`num ${tone(p.unrealized_r)}`}>{rMultiple(p.unrealized_r)}</td>
              <td>
                <div>{dateTime(p.entry_time)}</div>
                <div className="muted small">{ago(p.entry_time)}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const OUTCOME_TONES: Record<string, Tone> = {
  APPROVED: 'ok',
  REJECTED: 'bad',
  INVALID: 'bad',
  IGNORED: 'muted',
  NO_DECISION: 'muted',
}

export function SignalsTable({ signals, showStrategy = true }: { signals: SignalLogItem[]; showStrategy?: boolean }) {
  if (!signals.length) return <Empty title="No signals recorded" />
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Time</th>
            {showStrategy && <th>Strategy</th>}
            <th>Instrument</th>
            <th>Action</th>
            <th className="num">Entry</th>
            <th className="num">Stop</th>
            <th className="num">Target</th>
            <th>Outcome</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((s) => (
            <tr key={`${s.id}:${s.decision?.account_id ?? ''}`}>
              <td>
                <div>{dateTime(s.signal_time)}</div>
                <div className="muted small">{s.source.toLowerCase()}</div>
              </td>
              {showStrategy && (
                <td>
                  <Who instance={s.instance_id} />
                </td>
              )}
              <td>
                {s.instrument ?? '—'} <span className="muted small">{s.timeframe}</span>
              </td>
              <td>{s.action ? <span className={s.action === 'LONG' ? 'up' : s.action === 'SHORT' ? 'down' : ''}>{label(s.action)}</span> : '—'}</td>
              <td className="num">{decimal(s.entry)}</td>
              <td className="num">{decimal(s.stop_loss)}</td>
              <td className="num">{decimal(s.take_profit)}</td>
              <td>
                <Badge tone={OUTCOME_TONES[s.outcome] ?? 'muted'}>{s.outcome.replace('_', ' ').toLowerCase()}</Badge>
                {s.decision?.approved && s.decision.approved_qty && <div className="muted small">qty {qty(s.decision.approved_qty)}</div>}
              </td>
              <td className="reason">
                {s.outcome_code && <div className="mono small">{s.outcome_code}</div>}
                {s.reject_detail && <div className="muted small">{s.reject_detail}</div>}
                {s.reason && <div className="muted small">{s.reason}</div>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
