// "Explain this trade" (docs/04 §4.9): everything recorded about one trade, in the
// order it happened — the signal, the risk decision, the fills, the stop moves, the exit.

import { api } from '../api/client'
import type { Json, Signal, TradeExplain as Explain } from '../api/types'
import { between, dateTime, decimal, label, money, params, qty, rMultiple, shortId, tone } from '../lib/format'
import { usePoll } from '../lib/hooks'
import { Link } from '../lib/router'
import { Drawer } from './Drawer'
import { Badge, ErrorBox, Json as JsonView, KeyValues, Loading } from './ui'

function SignalBlock({ signal }: { signal: Signal }) {
  return (
    <KeyValues
      rows={[
        ['Signal', `${signal.action ?? '—'} ${signal.order_type.toLowerCase()} · ${signal.status.toLowerCase()}`],
        ['Decided at', `${dateTime(signal.signal_time)} (bar ${dateTime(signal.bar_time)})`],
        ['Entry / stop / target', `${decimal(signal.entry)} / ${decimal(signal.stop_loss)} / ${decimal(signal.take_profit)}`],
        ['Requested risk', signal.risk_pct ? `${decimal(signal.risk_pct)} %` : 'account default'],
        ['Confidence', signal.confidence ?? '—'],
        ['Reason', signal.reason ?? '—'],
        ['Metadata', Object.keys(signal.metadata).length ? params(signal.metadata) : '—'],
      ]}
    />
  )
}

function ruleName(rule: Json): string {
  if (rule && typeof rule === 'object' && !Array.isArray(rule)) {
    const named = rule.rule ?? rule.code ?? rule.name
    if (typeof named === 'string') return named
  }
  return 'rule'
}

function RuleTable({ rules }: { rules: Json[] }) {
  if (!rules.length) return <p className="muted">No rule results recorded.</p>
  return (
    <div className="table-wrap">
      <table className="table compact">
        <thead>
          <tr>
            <th>Rule</th>
            <th>Result</th>
            <th>Values</th>
          </tr>
        </thead>
        <tbody>
          {rules.map((rule, i) => {
            const obj = rule && typeof rule === 'object' && !Array.isArray(rule) ? rule : {}
            const passed = obj.passed ?? obj.ok
            const rest = Object.fromEntries(
              Object.entries(obj).filter(([k]) => !['rule', 'code', 'name', 'passed', 'ok'].includes(k)),
            )
            return (
              <tr key={i}>
                <td>{ruleName(rule)}</td>
                <td>
                  {passed === false ? <Badge tone="bad">failed</Badge> : passed === true ? <Badge tone="ok">passed</Badge> : '—'}
                </td>
                <td className="mono small">{params(rest) || '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function TradeExplainDrawer({ tradeId, onClose }: { tradeId: string; onClose: () => void }) {
  const { data, error } = usePoll(() => api.get<Explain>(`/trades/${tradeId}`), [tradeId], 0)
  return (
    <Drawer title={data ? `${data.trade.direction} ${data.trade.instrument} · ${data.trade.instance_id}` : 'Trade'} onClose={onClose}>
      <ErrorBox error={error} />
      {!data && !error && <Loading />}
      {data && <ExplainBody data={data} />}
    </Drawer>
  )
}

function ExplainBody({ data }: { data: Explain }) {
  const t = data.trade
  const costs = [t.commission, t.spread_cost, t.swap, t.funding].reduce((sum, v) => sum + Number(v), 0)
  return (
    <div className="explain">
      <section>
        <h3>Result</h3>
        <div className="explain-result">
          <div className={`big ${tone(t.net_pnl)}`}>{t.status === 'OPEN' ? 'open' : money(t.net_pnl, { signed: true })}</div>
          <div className={`big ${tone(t.r_multiple)}`}>{rMultiple(t.r_multiple)}</div>
          <Badge tone={t.status === 'OPEN' ? 'info' : 'muted'}>{t.exit_reason ? label(t.exit_reason) : t.status.toLowerCase()}</Badge>
        </div>
        <KeyValues
          rows={[
            ['Account', <Link to={`/accounts/${t.account_id}`}>{t.account_name}</Link>],
            ['Strategy', `${t.instance_id} · ${data.definition_name}`],
            ['Instrument', `${t.instrument} on ${t.venue} (${t.venue_symbol}), ${t.timeframe}`],
            ['Size', `${qty(t.qty)} · risk ${money(t.initial_risk)}`],
            ['Entry', `${decimal(t.entry_price)} at ${dateTime(t.entry_time)} (requested ${decimal(t.entry_requested)}, slippage ${decimal(t.entry_slippage)})`],
            ['Exit', t.exit_time ? `${decimal(t.exit_price)} at ${dateTime(t.exit_time)} (slippage ${decimal(t.exit_slippage)})` : 'still open'],
            ['Stop / target', `${decimal(t.initial_stop)} / ${decimal(t.initial_target)} initial · ${decimal(t.current_stop)} / ${decimal(t.current_target)} now`],
            ['Held', between(t.entry_time, t.exit_time)],
            ['Gross → net', `${money(t.gross_pnl, { signed: true })} − costs ${money(costs)} = ${money(t.net_pnl, { signed: true })}`],
            ['Costs', `commission ${money(t.commission)}, spread ${money(t.spread_cost)}, swap ${money(t.swap)}, funding ${money(t.funding)}`],
            ['Session', t.session ?? '—'],
          ]}
        />
      </section>

      <section>
        <h3>Why it entered — the signal</h3>
        <SignalBlock signal={data.entry_signal} />
        {Object.keys(data.entry_market_snapshot).length > 0 && (
          <details>
            <summary>Market data the strategy saw</summary>
            <JsonView value={data.entry_market_snapshot} />
          </details>
        )}
      </section>

      <section>
        <h3>Risk decision</h3>
        {data.decision ? (
          <>
            <KeyValues
              rows={[
                ['Decision', data.decision.approved ? <Badge tone="ok">approved</Badge> : <Badge tone="bad">rejected · {data.decision.primary_reason}</Badge>],
                ['Decided at', dateTime(data.decision.decided_at, { seconds: true })],
                ['Quantity', `${qty(data.decision.approved_qty)} approved (requested ${qty(data.decision.requested_qty)})`],
                ['Risk', `${money(data.decision.risk_amount)} (${data.decision.risk_pct ?? '—'} %)`],
              ]}
            />
            <RuleTable rules={data.decision.rule_results} />
            <details>
              <summary>Account state and quote used</summary>
              <JsonView value={{ account_state: data.decision.account_state, quote: data.decision.quote }} />
            </details>
          </>
        ) : (
          <p className="muted">No risk decision recorded for this trade.</p>
        )}
      </section>

      <section>
        <h3>Execution — orders and fills</h3>
        <div className="table-wrap">
          <table className="table compact">
            <thead>
              <tr>
                <th>Order</th>
                <th>Side</th>
                <th>Type</th>
                <th className="num">Qty</th>
                <th className="num">Requested</th>
                <th className="num">Filled at</th>
                <th>Status</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {data.orders.map((o) => (
                <tr key={o.id}>
                  <td>{label(o.purpose)}</td>
                  <td>{o.side}</td>
                  <td>{o.order_type.toLowerCase()}</td>
                  <td className="num">{qty(o.qty)}</td>
                  <td className="num">{decimal(o.requested_price)}</td>
                  <td className="num">{decimal(o.avg_fill_price)}</td>
                  <td>{o.status.toLowerCase()}{o.reject_reason ? ` · ${o.reject_reason}` : ''}</td>
                  <td>{dateTime(o.completed_at ?? o.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="table-wrap">
          <table className="table compact">
            <thead>
              <tr>
                <th>Fill</th>
                <th className="num">Qty</th>
                <th className="num">Price</th>
                <th className="num">Slippage</th>
                <th className="num">Spread cost</th>
                <th className="num">Commission</th>
                <th>Liquidity</th>
              </tr>
            </thead>
            <tbody>
              {data.fills.map((f) => (
                <tr key={f.id}>
                  <td>{dateTime(f.ts, { seconds: true })}</td>
                  <td className="num">{qty(f.qty)}</td>
                  <td className="num">{decimal(f.price)}</td>
                  <td className="num">{decimal(f.slippage)}</td>
                  <td className="num">{money(f.spread_cost)}</td>
                  <td className="num">{money(f.commission)}</td>
                  <td>{f.liquidity?.toLowerCase() ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {data.events.length > 0 && (
        <section>
          <h3>Stop and target changes</h3>
          <ul className="events">
            {data.events.map((e) => (
              <li key={e.id}>
                {dateTime(e.ts)} · {label(e.kind)} {decimal(e.old_value)} → {decimal(e.new_value)}
                {Object.keys(e.details).length > 0 && <span className="muted"> ({params(e.details)})</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3>Why it exited</h3>
        {t.status === 'OPEN' ? (
          <p className="muted">The trade is still open.</p>
        ) : (
          <>
            <p>
              <Badge tone="info">{label(t.exit_reason)}</Badge>
            </p>
            {data.exit_signal && <SignalBlock signal={data.exit_signal} />}
          </>
        )}
      </section>

      <section>
        <h3>Ledger</h3>
        <ul className="events">
          {data.ledger.map((entry, i) => (
            <li key={i}>
              {dateTime(entry.ts)} · {label(entry.kind)} <span className={tone(entry.amount)}>{money(entry.amount, { signed: true })}</span> → balance {money(entry.balance_after)}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3>Strategy version and account settings</h3>
        <KeyValues
          rows={[
            ['Definition', `${data.definition_id} v${data.version.definition_version}`],
            ['Version (config hash)', <span className="mono">{shortId(data.version.config_hash, 16)}</span>],
            ['Code hash', <span className="mono">{shortId(data.version.code_hash, 16)}</span>],
            ['Parameters', params(data.version.params) || '—'],
            ['Timeframes', [data.version.timeframe, ...data.version.context_timeframes].join(', ')],
            ['Account config', `v${data.account_config.version}: ${params(data.account_config.config)}`],
            ['Catalog', <span className="mono">{shortId(data.catalog_fingerprint, 16)}</span>],
          ]}
        />
      </section>
    </div>
  )
}
