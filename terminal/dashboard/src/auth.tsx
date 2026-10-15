import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ApiError, currentSession, login as apiLogin, logout as apiLogout, setUnauthorizedHandler } from './api/client'
import type { Role, Session } from './api/types'

interface AuthState {
  session: Session | null
  checking: boolean
  signIn: (username: string, password: string) => Promise<void>
  signOut: () => Promise<void>
  can: (role: Role) => boolean
}

const AuthContext = createContext<AuthState | null>(null)

const RANK: Record<Role, number> = { VIEWER: 0, OPERATOR: 1, ADMIN: 2 }

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    setUnauthorizedHandler(() => setSession(null))
    currentSession()
      .then(setSession)
      .catch((err: unknown) => {
        if (!(err instanceof ApiError && err.status === 401)) console.warn('session check failed', err)
        setSession(null)
      })
      .finally(() => setChecking(false))
  }, [])

  const signIn = useCallback(async (username: string, password: string) => {
    setSession(await apiLogin(username, password))
  }, [])

  const signOut = useCallback(async () => {
    try {
      await apiLogout()
    } finally {
      setSession(null)
    }
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      session,
      checking,
      signIn,
      signOut,
      can: (role) => !!session && RANK[session.user.role] >= RANK[role],
    }),
    [session, checking, signIn, signOut],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const state = useContext(AuthContext)
  if (!state) throw new Error('useAuth outside AuthProvider')
  return state
}
