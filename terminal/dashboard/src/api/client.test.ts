import { describe, expect, it } from 'vitest'
import { queryString } from './client'

describe('queryString', () => {
  it('skips empty values and repeats arrays', () => {
    expect(queryString({ scope: 'forward', q: '', run_id: null, limit: 50, x: undefined })).toBe('?scope=forward&limit=50')
    expect(queryString({ instance: ['a', 'b'], markers: 'all' })).toBe('?instance=a&instance=b&markers=all')
    expect(queryString({})).toBe('')
    expect(queryString({ q: 'fast=9 & slow' })).toBe('?q=fast%3D9+%26+slow')
  })
})
