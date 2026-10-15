// System: strategy instances (versions, runtime state, faults), recorded faults, runs
// (lab and forward), kill-switch history and the raw runtime status.

import { useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { Account, Fault, Instance, KillSwitches, Page, Run, RuntimeView } from '../api/types'
import { KillSwitchButton } from '../components/KillSwitch'
import { Leaderboard } from '../components/Leaderboard'
import { Badge, Card, Empty, ErrorBox, Json, KeyValues, Loading, Pager, StateBadge, Tabs } from '../components/ui'
import { ago, between, dateTime, params, shortId } from '../lib/format'
import { usePoll } from '../lib/hooks'
import { switchEventText, switchEventTone } from '../lib/killswitch'
import { Link, navigate } from '../lib/router'
import { instanceColor } from '../kcharts/trades'

type Tab = 'instances' | 'runs' | 'faults' | 'switches' | 'runtime'

function Instances({ instances, switches, onChanged }: { instances: Instance[]; switches: KillSwitches | null; onChanged: () => void }) {
  if (!instances.length) return <Empty title="No strategy instances registered">Run kterminal lab provision on the server.</Empty>
  const halted = new Set((switches?.switches ?? []).filter((s) => s.active && s.scope === 'STRATEGY').map((s) => s.scope_id))
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Instance</th>
            <th>Setup</th>
            <th>Parameters</th>
            <th>Version</th>
            <th>Status</th>
            <th>Runtime</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {instances.map((i) => (
            <tr key={i.id}>
              <td>
                <div className="who">
                  <span className="swatch" style={{ background: instanceColor(i.id) }} />
                  <div>
                    {i.account_id ? <Link to={`/accounts/${i.account_id}`}>{i.id}</Link> : i.id}
                    <div className="muted small">
                      {i.definition_id} · {i.kind.toLowerCase()}
                    </div>
                  </div>
                </div>
              </td>
              <td>
                {i.version?.instruments.join(', ')} · {i.version?.timeframe}
              </td>
              <td className="mono small">{params(i.version?.params)}</td>
              <td className="mono small" title={i.version?.config_hash}>
                {shortId(i.version?.config_hash, 10)} <span className="muted">({i.versions})</span>
              </td>
              <td>
                <Badge tone={i.enabled ? 'ok' : 'muted'}>{i.enabled ? 'enabled' : 'disabled'}</Badge> <Badge>{i.status.toLowerCase()}</Badge>
                {halted.has(i.id) && <Badge tone="bad">halted</Badge>}
              </td>
              <td>
                {i.runtime ? <StateBadge state={i.runtime.state} /> : <span className="muted">—</span>}
                {i.runtime?.fault ? <div className="down small">{String(i.runtime.fault)}</div> : null}
              </td>
              <td>
                <KillSwitchButton target={{ scope: 'STRATEGY', scopeId: i.id, label: `strategy ${i.id}` }} active={halted.has(i.id)} onChanged={onChanged} compact />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Runs() {
  const [offset, setOffset] = useState(0)
  const runs = usePoll(() => api.get<Page<Run>>('/runs', { limit: 25, offset }), [offset])
  if (!runs.data) return runs.error ? <ErrorBox error={runs.error} /> : <Loading />
  if (!runs.data.items.length) return <Empty title="No runs yet">Lab simulations (kterminal lab demo) and forward sessions appear here.</Empty>
  return (
    <>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Run</th>
              <th>Kind</th>
              <th>Status</th>
              <th>Data from → to</th>
              <th className="num">Accounts</th>
              <th className="num">Signals</th>
              <th className="num">Trades</th>
              <th>Recorded</th>
            </tr>
          </thead>
          <tbody>
            {runs.data.items.map((r) => (
              <tr key={r.id} className="clickable" onClick={() => navigate(`/runs/${r.id}`)}>
                <td>
                  {r.name || '—'} <span className="muted small mono">{shortId(r.id)}</span>
                </td>
                <td>{r.kind.toLowerCase().replace('_', ' ')}</td>
                <td>
                  <StateBadge state={r.status} />
                </td>
                <td>
                  {dateTime(r.started_at)} → {dateTime(r.finished_at)} <span className="muted small">{between(r.started_at, r.finished_at)}</span>
                </td>
                <td className="num">{r.accounts}</td>
                <td className="num">{r.signals}</td>
                <td className="num">{r.trades}</td>
                <td className="muted small">{ago(r.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pager total={runs.data.total} limit={25} offset={offset} onChange={setOffset} />
    </>
  )
}

function Faults() {
  const [offset, setOffset] = useState(0)
  const faults = usePoll(() => api.get<Page<Fault>>('/system/faults', { limit: 25, offset }), [offset])
  if (!faults.data) return faults.error ? <ErrorBox error={faults.error} /> : <Loading />
  if (!faults.data.items.length) return <Empty title="No faults recorded" />
  return (
    <>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Component</th>
              <th>Severity</th>
              <th>Strategy</th>
              <th>Message</th>
            </tr>
          </thead>
          <tbody>
            {faults.data.items.map((f) => (
              <tr key={f.id}>
                <td>{dateTime(f.ts)}</td>
                <td className="mono small">{f.component}</td>
                <td>
                  <Badge tone={f.severity === 'WARNING' ? 'warn' : 'bad'}>{f.severity.toLowerCase()}</Badge>
                </td>
                <td>{f.strategy_instance_id ?? '—'}</td>
                <td className="small">{f.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pager total={faults.data.total} limit={25} offset={offset} onChange={setOffset} />
    </>
  )
}

function SwitchHistory({ switches }: { switches: KillSwitches | null }) {
  if (!switches) return <Loading />
  if (!switches.history.length) return <Empty title="No kill switch was ever used" />
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Action</th>
            <th>Scope</th>
            <th>By</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {switches.history.map((e) => (
            <tr key={e.seq}>
              <td>{dateTime(e.ts, { seconds: true })}</td>
              <td>
                <Badge tone={switchEventTone(e)}>{e.action.replace('killswitch.', '')}</Badge>
              </td>
              <td>
                {e.scope === 'RUN' ? 'session' : e.scope.toLowerCase()}{' '}
                <span className="mono small">{e.scope_id === '*' ? '' : shortId(e.scope_id, 24)}</span>
              </td>
              <td>{e.actor_username ?? e.actor}</td>
              <td className="small">{switchEventText(e)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function SystemPage() {
  const [tab, setTab] = useState<Tab>('instances')
  const instances = usePoll(() => api.get<Instance[]>('/instances'), [])
  const switches = usePoll(() => api.get<KillSwitches>('/kill-switches'), [])
  const runtime = usePoll(() => api.get<RuntimeView>('/system/runtime'), [])
  const refresh = () => {
    instances.refresh()
    switches.refresh()
  }
  return (
    <div className="page">
      <ErrorBox error={instances.error ?? switches.error} />
      <Card>
        <Tabs<Tab>
          tabs={[
            { id: 'instances', label: `Instances${instances.data ? ` (${instances.data.length})` : ''}` },
            { id: 'runs', label: 'Runs' },
            { id: 'faults', label: 'Faults' },
            { id: 'switches', label: 'Kill switch history' },
            { id: 'runtime', label: 'Runtime status' },
          ]}
          value={tab}
          onChange={setTab}
        />
        {tab === 'instances' && (instances.data ? <Instances instances={instances.data} switches={switches.data} onChanged={refresh} /> : <Loading />)}
        {tab === 'runs' && <Runs />}
        {tab === 'faults' && <Faults />}
        {tab === 'switches' && <SwitchHistory switches={switches.data} />}
        {tab === 'runtime' &&
          (runtime.data ? (
            runtime.data.present ? (
              <>
                <KeyValues
                  rows={[
                    ['Status', runtime.data.status?.status ?? '—'],
                    ['Session', runtime.data.status?.session_id ?? '—'],
                    ['Run', runtime.data.status?.run_id ? <Link to={`/runs/${runtime.data.status.run_id}`}>{runtime.data.status.run_id}</Link> : '—'],
                    ['Age', `${runtime.data.age_seconds ?? '—'} s (stale after ${runtime.data.stale_after_seconds} s)`],
                  ]}
                />
                <Json value={runtime.data.status} />
              </>
            ) : (
              <Empty title="No forward session yet">The forward runtime writes its status to system_state 'paper.runtime'.</Empty>
            )
          ) : (
            <Loading />
          ))}
      </Card>
    </div>
  )
}

export function RunPage({ id }: { id: string }) {
  const run = usePoll(() => api.get<Run>(`/runs/${id}`), [id])
  const accounts = usePoll(() => api.get<Page<Account>>('/accounts', { run_id: id, limit: 500 }), [id])
  const r = run.data
  if (!r) return <div className="page">{run.error ? <ErrorBox error={run.error} /> : <Loading />}</div>
  return (
    <div className="page">
      <Card
        title={
          <>
            {r.name || 'Run'} <span className="muted small mono">{r.id}</span>
          </>
        }
        actions={
          <Link to={`/trades?run_id=${r.id}`} className="btn small">
            Trades
          </Link>
        }
      >
        <KeyValues
          rows={[
            ['Kind', r.kind.toLowerCase().replace('_', ' ')],
            ['Status', <StateBadge state={r.status} />],
            ['Data', `${dateTime(r.started_at)} → ${dateTime(r.finished_at)} (${between(r.started_at, r.finished_at)})`],
            ['Instances', r.instances.join(', ') || '—'],
            ['Signals / trades', `${r.signals} / ${r.trades}`],
            ['Summary', r.summary ? params(r.summary) : '—'],
            ...(r.error ? ([['Error', <span className="down">{r.error}</span>]] as [string, ReactNode][]) : []),
          ]}
        />
        {r.kind === 'LAB_SIMULATION' && (
          <p className="muted small">
            Lab simulations run on the data they were given (the demo uses a synthetic random walk); their accounts are
            separate from the forward accounts and never mix with them.
          </p>
        )}
      </Card>
      <Card title="Accounts in this run">
        {accounts.data ? <Leaderboard accounts={accounts.data.items} /> : <Loading />}
      </Card>
    </div>
  )
}
