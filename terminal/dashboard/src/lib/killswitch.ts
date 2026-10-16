// Kill-switch audit entries (GET /kill-switches → history) in words.

import type { Json, KillSwitchEvent } from '../api/types'
import { dateTime } from './format'
import type { HealthTone } from './runtime'

export function switchEventTone(event: Pick<KillSwitchEvent, 'action'>): HealthTone {
  if (event.action === 'killswitch.activate') return 'bad'
  if (event.action === 'killswitch.deactivate') return 'ok'
  return 'info'
}

function count(value: Json | undefined, one: string, many: string): string {
  const n = Array.isArray(value) ? value.length : 0
  return `${n} ${n === 1 ? one : many}`
}

/** activate/deactivate: the reason (and "· close positions"); applied: what the session
 * applied and from which minute on. */
export function switchEventText(event: Pick<KillSwitchEvent, 'action' | 'data'>): string {
  const data = event.data
  if (event.action === 'killswitch.applied') {
    const state = data.state && typeof data.state === 'object' && !Array.isArray(data.state) ? data.state : {}
    const from = typeof data.effective_from === 'string' ? dateTime(data.effective_from) : '—'
    return `from ${from}: global ${state.global === true ? 'ON' : 'off'}, ${count(state.accounts, 'account', 'accounts')}, ${count(
      state.strategies,
      'strategy',
      'strategies',
    )}`
  }
  const reason = typeof data.reason === 'string' ? data.reason : ''
  return data.close_positions === true ? `${reason} · close positions` : reason
}
