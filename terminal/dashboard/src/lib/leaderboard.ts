// Sorting and filtering the leaderboard in the browser. ~50 forward accounts arrive in
// one response; re-sorting and filtering them locally is instant and needs no request.
// The rules match the API's (kterminal/api/queries/accounts.py): accounts without a
// value for the sort key come last in either direction, ties are broken by profit factor.

import type { Account } from '../api/types'
import { toNumber } from './format'

export type SortKey =
  | 'average_r'
  | 'return_pct'
  | 'net_pnl'
  | 'max_drawdown_pct'
  | 'win_rate'
  | 'trades'
  | 'profit_factor'
  | 'expectancy'
  | 'equity'
  | 'open_positions'
  | 'name'
  | 'instance'

export type SortDir = 'asc' | 'desc'

export interface Sort {
  key: SortKey
  dir: SortDir
}

/** Appendix A: rank by expectancy in R. */
export const DEFAULT_SORT: Sort = { key: 'average_r', dir: 'desc' }

function sortValue(account: Account, key: SortKey): number | string | null {
  if (key === 'name') return account.name.toLowerCase()
  if (key === 'instance') return (account.instance_id ?? '').toLowerCase()
  const value = account.metrics[key]
  return typeof value === 'number' ? value : toNumber(value)
}

export function sortAccounts(accounts: Account[], sort: Sort): Account[] {
  const sign = sort.dir === 'asc' ? 1 : -1
  const present = accounts.filter((a) => sortValue(a, sort.key) !== null)
  const missing = accounts.filter((a) => sortValue(a, sort.key) === null)
  present.sort((a, b) => {
    const va = sortValue(a, sort.key)!
    const vb = sortValue(b, sort.key)!
    if (va < vb) return -sign
    if (va > vb) return sign
    const pa = toNumber(a.metrics.profit_factor) ?? -Infinity
    const pb = toNumber(b.metrics.profit_factor) ?? -Infinity
    if (pa !== pb) return (pa < pb ? -1 : 1) * sign
    return a.name.localeCompare(b.name)
  })
  missing.sort((a, b) => a.name.localeCompare(b.name))
  return [...present, ...missing]
}

/** Clicking a column: a new column sorts "best first", the same column flips. */
export function nextSort(current: Sort, key: SortKey): Sort {
  if (current.key === key) return { key, dir: current.dir === 'desc' ? 'asc' : 'desc' }
  const ascendingFirst: SortKey[] = ['max_drawdown_pct', 'name', 'instance']
  return { key, dir: ascendingFirst.includes(key) ? 'asc' : 'desc' }
}

export interface AccountFilter {
  strategy?: string
  instrument?: string
  timeframe?: string
  query?: string
  halted?: boolean
}

export function filterAccounts(accounts: Account[], filter: AccountFilter): Account[] {
  const needle = (filter.query ?? '').trim().toLowerCase()
  return accounts.filter((a) => {
    if (filter.strategy && a.definition_id !== filter.strategy) return false
    if (filter.instrument && !(a.version?.instruments ?? []).includes(filter.instrument)) return false
    if (filter.timeframe && a.version?.timeframe !== filter.timeframe) return false
    if (filter.halted && !a.halted) return false
    if (needle) {
      const haystack = [
        a.name,
        a.instance_id,
        a.instance_name,
        a.definition_id,
        a.definition_name,
        ...(a.version?.instruments ?? []),
        a.version?.timeframe,
        ...Object.entries(a.version?.params ?? {}).map(([k, v]) => `${k}=${String(v)}`),
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      if (!haystack.includes(needle)) return false
    }
    return true
  })
}

const TIMEFRAME_MINUTES: Record<string, number> = { m: 1, h: 60, D: 1440, W: 10080, M: 43200 }

export function timeframeMinutes(code: string): number {
  const match = /^(\d+)([mhDWM])$/.exec(code)
  return match ? Number(match[1]) * TIMEFRAME_MINUTES[match[2]] : Number.MAX_SAFE_INTEGER
}

export interface Facets {
  strategies: { id: string; name: string }[]
  instruments: string[]
  timeframes: string[]
}

/** The values the leaderboard's filter menus offer. */
export function facets(accounts: Account[]): Facets {
  const strategies = new Map<string, string>()
  const instruments = new Set<string>()
  const timeframes = new Set<string>()
  for (const a of accounts) {
    if (a.definition_id) strategies.set(a.definition_id, a.definition_name ?? a.definition_id)
    for (const i of a.version?.instruments ?? []) instruments.add(i)
    if (a.version?.timeframe) timeframes.add(a.version.timeframe)
  }
  return {
    strategies: [...strategies].map(([id, name]) => ({ id, name })).sort((a, b) => a.id.localeCompare(b.id)),
    instruments: [...instruments].sort(),
    timeframes: [...timeframes].sort((a, b) => timeframeMinutes(a) - timeframeMinutes(b)),
  }
}

/** Totals over a set of accounts (shown under the leaderboard). */
export function totals(accounts: Account[]): { netPnl: number; equity: number; start: number; open: number; trades: number } {
  let netPnl = 0
  let equity = 0
  let start = 0
  let open = 0
  let trades = 0
  for (const a of accounts) {
    netPnl += toNumber(a.metrics.net_pnl) ?? 0
    equity += toNumber(a.metrics.equity) ?? 0
    start += toNumber(a.metrics.starting_balance) ?? 0
    open += a.metrics.open_positions
    trades += a.metrics.trades
  }
  return { netPnl, equity, start, open, trades }
}
