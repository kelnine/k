import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { useAuth } from '../auth'

export function Login() {
  const { signIn } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await signIn(username, password)
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) setError('Too many failed attempts. Try again later.')
      else if (err instanceof ApiError && err.status === 401) setError('Wrong username or password.')
      else setError(err instanceof Error ? err.message : String(err))
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <form className="login-card" onSubmit={submit}>
        <div className="brand big">
          K<span className="brand-dot">·</span>Terminal
        </div>
        <p className="muted">Paper trading lab — sign in to watch the strategies.</p>
        <label className="field">
          <span>Username</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus required />
        </label>
        <label className="field">
          <span>Password</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        {error && <div className="error-box">{error}</div>}
        <button className="btn primary wide" type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="muted small">
          No account yet? On the server: <code>kterminal users add NAME --role ADMIN</code>
        </p>
      </form>
    </div>
  )
}
