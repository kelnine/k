import { useEffect, useMemo, useRef, useState } from 'react'
import type { DataAdapter, SymbolInfo, Ticker, Timeframe } from '../data'
import { TIMEFRAMES } from '../data'
import type { DrawingTool } from '../engine/drawings'
import { formatPrice } from '../engine/utils'
import { INDICATORS } from '../indicators'
import { BotFeed } from './BotFeed'
import { ChartView } from './ChartView'

type Layout = '1' | '2h' | '2v' | '4'

interface CellConfig {
  symbol: string
  tf: Timeframe
  indicators: string[]
}

interface PersistedState {
  layout: Layout
  cells: CellConfig[]
  watchlist: string[]
}

const DEFAULT_STATE: PersistedState = {
  layout: '1',
  cells: [
    { symbol: 'BTCUSDT', tf: '1h', indicators: ['ma20', 'ma50'] },
    { symbol: 'ETHUSDT', tf: '1h', indicators: [] },
    { symbol: 'SOLUSDT', tf: '1h', indicators: [] },
    { symbol: 'BNBUSDT', tf: '1h', indicators: [] },
  ],
  watchlist: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT'],
}

const STATE_KEY = 'kcharts:state'

function loadState(): PersistedState {
  try {
    const raw = localStorage.getItem(STATE_KEY)
    if (!raw) return DEFAULT_STATE
    const parsed = JSON.parse(raw) as Partial<PersistedState>
    return {
      layout: parsed.layout ?? DEFAULT_STATE.layout,
      cells: parsed.cells?.length === 4 ? parsed.cells : DEFAULT_STATE.cells,
      watchlist: parsed.watchlist ?? DEFAULT_STATE.watchlist,
    }
  } catch {
    return DEFAULT_STATE
  }
}

const CELL_COUNT: Record<Layout, number> = { '1': 1, '2h': 2, '2v': 2, '4': 4 }

const TOOLS: { id: DrawingTool; label: string; title: string }[] = [
  { id: 'cursor', label: '✛', title: 'Cursor (pan/select)' },
  { id: 'trendline', label: '╱', title: 'Trend line' },
  { id: 'hline', label: '─', title: 'Horizontal level' },
  { id: 'fib', label: '𝒇', title: 'Fibonacci retracement' },
  { id: 'text', label: 'T', title: 'Text note' },
]

// ---------------------------------------------------------------- watchlist row

function WatchRow({
  adapter,
  symbol,
  selected,
  onSelect,
  onRemove,
}: {
  adapter: DataAdapter
  symbol: string
  selected: boolean
  onSelect(): void
  onRemove(): void
}) {
  const [tick, setTick] = useState<Ticker | null>(null)
  const [flash, setFlash] = useState<'up' | 'down' | null>(null)
  const lastRef = useRef<number | null>(null)

  useEffect(() => {
    const unsub = adapter.subscribeTicker(symbol, (t) => {
      if (lastRef.current !== null && t.last !== lastRef.current) {
        setFlash(t.last > lastRef.current ? 'up' : 'down')
        setTimeout(() => setFlash(null), 400)
      }
      lastRef.current = t.last
      setTick(t)
    })
    return unsub
  }, [adapter, symbol])

  return (
    <div className={`watch-row${selected ? ' selected' : ''}`} onClick={onSelect}>
      <span className="watch-symbol">{symbol.replace(/USDT$/, '')}</span>
      <span className={`watch-price${flash ? ` flash-${flash}` : ''}`}>
        {tick ? formatPrice(tick.last) : '…'}
      </span>
      <span className={`watch-change ${tick && tick.changePct >= 0 ? 'pos' : 'neg'}`}>
        {tick ? `${tick.changePct >= 0 ? '+' : ''}${tick.changePct.toFixed(2)}%` : ''}
      </span>
      <button
        className="watch-remove"
        title="Remove"
        onClick={(e) => {
          e.stopPropagation()
          onRemove()
        }}
      >
        ×
      </button>
    </div>
  )
}

// ---------------------------------------------------------------- symbol search

function SymbolSearch({ adapter, onPick }: { adapter: DataAdapter; onPick(s: string): void }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [results, setResults] = useState<SymbolInfo[]>([])
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    const t = setTimeout(() => {
      adapter.searchSymbols(query).then((r) => {
        if (!cancelled) setResults(r)
      })
    }, 150)
    return () => {
      cancelled = true
      clearTimeout(t)
    }
  }, [adapter, query, open])

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  return (
    <div className="symbol-search" ref={boxRef}>
      <input
        placeholder="Search symbol…"
        value={query}
        onFocus={() => setOpen(true)}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && results[0]) {
            onPick(results[0].symbol)
            setOpen(false)
            setQuery('')
          }
          if (e.key === 'Escape') setOpen(false)
        }}
      />
      {open && results.length > 0 && (
        <div className="search-dropdown">
          {results.map((s) => (
            <div
              key={s.symbol}
              className="search-item"
              onClick={() => {
                onPick(s.symbol)
                setOpen(false)
                setQuery('')
              }}
            >
              <span className="search-symbol">{s.symbol}</span>
              <span className="search-desc">{s.description}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- app

export function App({ adapter }: { adapter: DataAdapter }) {
  const initial = useMemo(loadState, [])
  const [layout, setLayout] = useState<Layout>(initial.layout)
  const [cells, setCells] = useState<CellConfig[]>(initial.cells)
  const [watchlist, setWatchlist] = useState<string[]>(initial.watchlist)
  const [activeCell, setActiveCell] = useState(0)
  const [tool, setTool] = useState<DrawingTool>('cursor')
  const [indMenuOpen, setIndMenuOpen] = useState(false)
  const indMenuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    localStorage.setItem(STATE_KEY, JSON.stringify({ layout, cells, watchlist }))
  }, [layout, cells, watchlist])

  useEffect(() => {
    if (!indMenuOpen) return
    const close = (e: MouseEvent) => {
      if (!indMenuRef.current?.contains(e.target as Node)) setIndMenuOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [indMenuOpen])

  const count = CELL_COUNT[layout]
  const active = cells[Math.min(activeCell, count - 1)]

  function updateActive(patch: Partial<CellConfig>): void {
    setCells((cs) => cs.map((c, i) => (i === Math.min(activeCell, count - 1) ? { ...c, ...patch } : c)))
  }

  function toggleIndicator(id: string): void {
    const has = active.indicators.includes(id)
    updateActive({ indicators: has ? active.indicators.filter((x) => x !== id) : [...active.indicators, id] })
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          KCharts<span className="brand-dot">.</span>
        </div>
        <SymbolSearch adapter={adapter} onPick={(s) => updateActive({ symbol: s })} />
        <div className="tf-group">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              className={`tf-btn${active.tf === tf ? ' on' : ''}`}
              onClick={() => updateActive({ tf })}
            >
              {tf}
            </button>
          ))}
        </div>
        <div className="ind-menu" ref={indMenuRef}>
          <button className="bar-btn" onClick={() => setIndMenuOpen((o) => !o)}>
            ƒ Indicators{active.indicators.length ? ` · ${active.indicators.length}` : ''}
          </button>
          {indMenuOpen && (
            <div className="ind-dropdown">
              {INDICATORS.map((ind) => (
                <label key={ind.id} className="ind-item">
                  <input
                    type="checkbox"
                    checked={active.indicators.includes(ind.id)}
                    onChange={() => toggleIndicator(ind.id)}
                  />
                  <span>{ind.name}</span>
                  <span className="ind-kind">{ind.kind === 'pane' ? 'pane' : 'overlay'}</span>
                </label>
              ))}
            </div>
          )}
        </div>
        <div className="layout-group">
          {(['1', '2h', '2v', '4'] as Layout[]).map((l) => (
            <button
              key={l}
              title={`${CELL_COUNT[l]} chart${CELL_COUNT[l] > 1 ? 's' : ''}`}
              className={`layout-btn${layout === l ? ' on' : ''}`}
              onClick={() => setLayout(l)}
            >
              {l === '1' ? '▣' : l === '2h' ? '◫' : l === '2v' ? '⊟' : '⊞'}
            </button>
          ))}
        </div>
        <div className="spacer" />
        <div className={`feed-badge ${adapter.id}`}>
          {adapter.id === 'binance' ? '● Live · Binance' : '● Demo data (offline)'}
        </div>
      </header>

      <div className="body">
        <aside className="tool-rail">
          {TOOLS.map((t) => (
            <button
              key={t.id}
              title={t.title}
              className={`tool-btn${tool === t.id ? ' on' : ''}`}
              onClick={() => setTool(t.id)}
            >
              {t.label}
            </button>
          ))}
        </aside>

        <main className={`grid layout-${layout}`}>
          {cells.slice(0, count).map((cell, i) => (
            <ChartView
              key={i}
              adapter={adapter}
              symbol={cell.symbol}
              tf={cell.tf}
              indicators={cell.indicators}
              tool={tool}
              active={i === Math.min(activeCell, count - 1)}
              showFrame={count > 1}
              onActivate={() => setActiveCell(i)}
              onToolFinished={() => setTool('cursor')}
            />
          ))}
        </main>

        <aside className="watchlist">
          <div className="watch-header">Watchlist</div>
          <div className="watch-rows">
            {watchlist.map((s) => (
              <WatchRow
                key={s}
                adapter={adapter}
                symbol={s}
                selected={s === active.symbol}
                onSelect={() => updateActive({ symbol: s })}
                onRemove={() => setWatchlist((w) => w.filter((x) => x !== s))}
              />
            ))}
          </div>
          <WatchAdd
            adapter={adapter}
            onAdd={(s) => setWatchlist((w) => (w.includes(s) ? w : [...w, s]))}
          />
          <BotFeed adapter={adapter} symbols={watchlist} />
        </aside>
      </div>
    </div>
  )
}

function WatchAdd({ adapter, onAdd }: { adapter: DataAdapter; onAdd(s: string): void }) {
  const [adding, setAdding] = useState(false)
  if (!adding) {
    return (
      <button className="watch-add" onClick={() => setAdding(true)}>
        + Add symbol
      </button>
    )
  }
  return (
    <div className="watch-add-box">
      <SymbolSearch
        adapter={adapter}
        onPick={(s) => {
          onAdd(s)
          setAdding(false)
        }}
      />
      <button className="watch-add" onClick={() => setAdding(false)}>
        Cancel
      </button>
    </div>
  )
}
