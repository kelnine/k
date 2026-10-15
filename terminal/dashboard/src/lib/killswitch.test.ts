import { describe, expect, it } from 'vitest'
import { switchEventText, switchEventTone } from './killswitch'

describe('kill-switch history', () => {
  it('colours changes and applications', () => {
    expect(switchEventTone({ action: 'killswitch.activate' })).toBe('bad')
    expect(switchEventTone({ action: 'killswitch.deactivate' })).toBe('ok')
    expect(switchEventTone({ action: 'killswitch.applied' })).toBe('info')
  })

  it('describes an operator change by its reason', () => {
    expect(
      switchEventText({ action: 'killswitch.activate', data: { reason: 'news spike', close_positions: true } }),
    ).toBe('news spike · close positions')
    expect(switchEventText({ action: 'killswitch.deactivate', data: { reason: 'calm', close_positions: false } })).toBe(
      'calm',
    )
  })

  it('describes what a session applied and from when', () => {
    const text = switchEventText({
      action: 'killswitch.applied',
      data: {
        effective_from: '2026-01-05T21:20:00+00:00',
        state: { global: true, accounts: ['a1'], strategies: [] },
      },
    })
    expect(text).toBe('from 2026-01-05 21:20: global ON, 1 account, 0 strategies')
  })
})
