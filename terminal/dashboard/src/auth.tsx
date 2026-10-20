import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ApiError, authOptions, currentSession, localSignIn, login as apiLogin, logout as apiLogout, setUnauthorizedHandler } from './api/client'
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
  // A dashboard without sign-in (KT_AUTH__LOCAL_NO_LOGIN): an ended or expired
  // session is simply opened again instead of showing the sign-in page.
  const noLogin = useRef(false)
  // One local sign-in at a time: parallel ones would leave a cookie and a CSRF
  // token from different sessions.
  const reopening = useRef<Promise<void> | null>(null)

  useEffect(() => {
    const reopen = () => {
      if (!noLogin.current) {
        setSession(null)
        return
      }
      reopening.current ??= localSignIn()
        .then(setSession)
        .catch(() => setSession(null))
        .finally(() => {
          reopening.current = null
        })
    }
    setUnauthorizedHandler(reopen)

    const start = async (): Promise<Session | null> => {
      try {
        return await currentSession()
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 401)) {
          console.warn('session check failed', err)
          return null
        }
      }
      const options = await authOptions()
      noLogin.current = options.local_no_login
      return options.local_no_login ? await localSignIn() : null
    }
    start()
      .then((opened) => {
        if (opened?.local) noLogin.current = true
        setSession(opened)
      })
      .catch((err: unknown) => {
        console.warn('sign-in check failed', err)
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
