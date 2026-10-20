import { describe, expect, it, vi } from 'vitest'
import { api, authOptions, localSignIn, queryString, setCsrfToken } from './client'

describe('queryString', () => {
  it('skips empty values and repeats arrays', () => {
    expect(queryString({ scope: 'forward', q: '', run_id: null, limit: 50, x: undefined })).toBe('?scope=forward&limit=50')
    expect(queryString({ instance: ['a', 'b'], markers: 'all' })).toBe('?instance=a&instance=b&markers=all')
    expect(queryString({})).toBe('')
    expect(queryString({ q: 'fast=9 & slow' })).toBe('?q=fast%3D9+%26+slow')
  })
})

describe('local sign-in', () => {
  it('opens the local session and sends its CSRF token on the next change', async () => {
    const calls: { url: string; method: string; csrf: string | null }[] = []
    const session = { user: { id: 'u', username: 'local', role: 'ADMIN' }, csrf_token: 'tok-1', expires_at: '2026-10-21T00:00:00Z', local: true }
    vi.stubGlobal('fetch', async (url: string, init: RequestInit) => {
      const headers = (init.headers ?? {}) as Record<string, string>
      calls.push({ url, method: init.method ?? 'GET', csrf: headers['X-CSRF-Token'] ?? null })
      const body = url.endsWith('/auth/options') ? { local_no_login: true } : url.endsWith('/auth/local') ? session : {}
      return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    try {
      expect(await authOptions()).toEqual({ local_no_login: true })
      expect((await localSignIn()).local).toBe(true)
      await api.post('/kill-switches', { scope: 'GLOBAL' })
      expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual(['GET /api/v1/auth/options', 'POST /api/v1/auth/local', 'POST /api/v1/kill-switches'])
      expect(calls[2].csrf).toBe('tok-1')
    } finally {
      vi.unstubAllGlobals()
      setCsrfToken(null)
    }
  })
})
