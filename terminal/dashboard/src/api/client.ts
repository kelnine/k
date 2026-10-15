// The one place that talks to the API: same-origin fetch with the session cookie,
// the CSRF token on state-changing requests, and a global "signed out" signal on 401.

import type { Session } from './types'

export class ApiError extends Error {
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

let csrfToken: string | null = null
let onUnauthorized: () => void = () => {}

export function setCsrfToken(token: string | null): void {
  csrfToken = token
}

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler
}

export type Params = Record<string, string | number | boolean | null | undefined | string[]>

/** `?a=1&b=x&b=y` from params, skipping empty values. */
export function queryString(params: Params = {}): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue
    if (Array.isArray(value)) for (const item of value) search.append(key, item)
    else search.append(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

async function request<T>(method: string, path: string, params?: Params, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET' && csrfToken) headers['X-CSRF-Token'] = csrfToken
  let response: Response
  try {
    response = await fetch(`/api/v1${path}${queryString(params)}`, {
      method,
      headers,
      credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'NETWORK', 'the API cannot be reached')
  }
  if (response.status === 204) return undefined as T
  let payload: unknown = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }
  if (!response.ok) {
    const data = (payload ?? {}) as { code?: string; message?: string; detail?: unknown }
    const message =
      data.message || (Array.isArray(data.detail) ? 'invalid request' : '') || response.statusText
    const error = new ApiError(response.status, data.code ?? `HTTP_${response.status}`, message)
    if (response.status === 401 && path !== '/auth/login') onUnauthorized()
    throw error
  }
  return payload as T
}

export const api = {
  get: <T>(path: string, params?: Params) => request<T>('GET', path, params),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, undefined, body ?? {}),
}

export async function login(username: string, password: string): Promise<Session> {
  const session = await api.post<Session>('/auth/login', { username, password })
  setCsrfToken(session.csrf_token)
  return session
}

export async function currentSession(): Promise<Session> {
  const session = await api.get<Session>('/auth/me')
  setCsrfToken(session.csrf_token)
  return session
}

export async function logout(): Promise<void> {
  try {
    await api.post<void>('/auth/logout')
  } finally {
    setCsrfToken(null)
  }
}
