import { describe, expect, it } from 'vitest'
import { ago, between, dateTime, decimal, fixed, label, money, params, pct, qty, ratio, rMultiple, ruleDetails, seconds, shortId, toNumber, tone } from './format'

describe('numbers', () => {
  it('parses decimal strings and refuses junk', () => {
    expect(toNumber('51372.7500')).toBe(51372.75)
    expect(toNumber('-0.5')).toBe(-0.5)
    expect(toNumber(null)).toBeNull()
    expect(toNumber('')).toBeNull()
    expect(toNumber('NaN')).toBeNull()
    expect(toNumber('Infinity')).toBeNull()
  })

  it('formats money with grouping, sign and the true minus', () => {
    expect(money('50000.0000')).toBe('$50,000.00')
    expect(money('1372.96', { signed: true })).toBe('+$1,372.96')
    expect(money('-965.24', { signed: true })).toBe('−$965.24')
    expect(money('-12')).toBe('−$12.00')
    expect(money('0', { signed: true })).toBe('$0.00')
    expect(money(null)).toBe('—')
    expect(money('103216.125', { compact: true })).toBe('$103.2K')
    expect(money('2500000', { compact: true })).toBe('$2.50M')
    expect(money('10', { currency: 'EUR' })).toBe('10.00 EUR')
  })

  it('formats percentages, ratios and R multiples', () => {
    expect(pct('2.85', { signed: true })).toBe('+2.85%')
    expect(pct('-0.6')).toBe('−0.60%')
    expect(ratio('0.6364')).toBe('63.6%')
    expect(ratio(null)).toBe('—')
    expect(rMultiple('0.5817')).toBe('+0.58R')
    expect(rMultiple('-1')).toBe('−1.00R')
    expect(rMultiple('0')).toBe('0.00R')
    expect(fixed('1.364', 2)).toBe('1.36')
  })

  it('shows stored prices without trailing zeros but with enough decimals', () => {
    expect(decimal('4345.7800000000')).toBe('4,345.78')
    expect(decimal('1.1712300000')).toBe('1.17123')
    expect(decimal('45.0000000000')).toBe('45.00')
    expect(decimal('0.0300000000')).toBe('0.03')
    expect(decimal('-12.5')).toBe('−12.50')
    expect(decimal(null)).toBe('—')
    expect(qty('0.0900000000')).toBe('0.09')
    expect(qty('3.0000000000')).toBe('3')
  })

  it('tones signed values', () => {
    expect(tone('1.5')).toBe('up')
    expect(tone('-0.01')).toBe('down')
    expect(tone('0')).toBe('')
    expect(tone(null)).toBe('')
  })
})

describe('time', () => {
  const now = Date.parse('2026-01-14T04:01:00Z')

  it('prints UTC date-times', () => {
    expect(dateTime('2026-01-14T04:00:00Z')).toBe('2026-01-14 04:00')
    expect(dateTime('2026-01-14T04:00:05Z', { seconds: true })).toBe('2026-01-14 04:00:05')
    expect(dateTime('2026-01-14T00:30:00-05:00')).toBe('2026-01-14 05:30')
    expect(dateTime(null)).toBe('—')
    expect(dateTime('not a date')).toBe('—')
  })

  it('says how long ago', () => {
    expect(ago('2026-01-14T04:00:55Z', now)).toBe('5s ago')
    expect(ago('2026-01-14T03:58:00Z', now)).toBe('3m ago')
    expect(ago('2026-01-14T01:00:00Z', now)).toBe('3h ago')
    expect(ago('2026-01-10T04:01:00Z', now)).toBe('4d ago')
    expect(ago('2026-01-14T04:02:00Z', now)).toBe('just now')
  })

  it('prints durations', () => {
    expect(seconds(4.2)).toBe('4s')
    expect(seconds(185)).toBe('3m 05s')
    expect(seconds(5100)).toBe('1h 25m')
    expect(seconds(183600)).toBe('2d 3h')
    expect(seconds(null)).toBe('—')
    expect(between('2026-01-14T02:25:00Z', '2026-01-14T03:50:00Z')).toBe('1h 25m')
    expect(between('2026-01-14T04:00:00Z', null, now)).toBe('1m 00s')
  })
})

describe('labels', () => {
  it('turns codes and parameters into text', () => {
    expect(label('SESSION_CLOSE')).toBe('Session close')
    expect(label('TAKE_PROFIT')).toBe('Take profit')
    expect(label(null)).toBe('—')
    expect(params({ fast: 9, slow: 21, reward_risk: '2' })).toBe('fast=9 slow=21 reward_risk=2')
    expect(params({ window: { start: '0930' } })).toBe('window={"start":"0930"}')
    expect(params(null)).toBe('')
    expect(shortId('01a13cc6-efc4-7214-b50d-b08ba7a7a527')).toBe('a7a7a527')
    expect(shortId('01a13cc6-efc4-7214-b50d-b08ba7a7a528')).not.toBe(shortId('01a13cc6-efc4-7214-b50d-b08ba7a7a527'))
    expect(shortId('6ee1b0891c03a9f2', 12)).toBe('6ee1b0891c03')
  })
})

describe('ruleDetails', () => {
  it('shows the message and the values of a rule result, nothing empty', () => {
    expect(ruleDetails({ rule: 'market_open', passed: true, values: {}, message: '' })).toBe('')
    expect(ruleDetails({ rule: 'max_open_positions', passed: true, values: { open: 0, limit: 1 }, message: '' })).toBe(
      'open=0 · limit=1',
    )
    expect(
      ruleDetails({
        rule: 'kill_switch',
        passed: false,
        values: {},
        message: 'GLOBAL kill switch active: CPI release drill',
      }),
    ).toBe('GLOBAL kill switch active: CPI release drill')
    expect(
      ruleDetails({ rule: 'position_size', values: { qty: '115.2', risk_pct: '0.499676638617208326', note: null } }),
    ).toBe('qty=115.2 · risk_pct=0.499676')
  })
})
