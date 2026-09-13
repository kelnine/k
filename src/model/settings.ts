import { TRADER_DEFAULTS, type TraderOptions } from './autotrader'

/**
 * The one trader setting the UI exposes, held outside React so the chart
 * overlay (which computes inside the engine, with no access to component
 * state) and the panel always run the model the same way.
 */

let entryStyle: TraderOptions['entryStyle'] = TRADER_DEFAULTS.entryStyle

export function getEntryStyle(): TraderOptions['entryStyle'] {
  return entryStyle
}

export function setEntryStyle(style: TraderOptions['entryStyle']): void {
  entryStyle = style
}

/** Trader overrides to hand `runModel`, wherever it is called from. */
export function traderOptions(): Partial<TraderOptions> {
  return { entryStyle }
}
