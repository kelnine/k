// Kill switches (OPERATOR and up). Halting is one click plus a reason; releasing
// re-enables trading, so the API asks for the operator's password again.

import { useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { KillSwitch, KillSwitchScope } from '../api/types'
import { useAuth } from '../auth'
import { ago, dateTime } from '../lib/format'
import { Modal } from './Drawer'
import { Badge } from './ui'

interface Target {
  scope: KillSwitchScope
  scopeId: string
  label: string
}

export function KillSwitchButton({
  target,
  active,
  onChanged,
  compact = false,
  noun,
}: {
  target: Target
  active: boolean
  onChanged: () => void
  compact?: boolean
  noun?: string // "account", "strategy": tells two buttons side by side apart
}) {
  const { can } = useAuth()
  const [open, setOpen] = useState(false)
  if (!can('OPERATOR')) return null
  const verb = active ? 'Release' : 'Halt'
  const text = target.scope === 'GLOBAL' && !active ? 'Halt all trading' : noun ? `${verb} ${noun}` : verb
  return (
    <>
      <button className={`btn ${active ? '' : 'danger'} ${compact ? 'small' : ''}`} onClick={() => setOpen(true)}>
        {text}
      </button>
      {open && (
        <KillSwitchDialog
          target={target}
          activate={!active}
          onClose={() => setOpen(false)}
          onDone={() => {
            setOpen(false)
            onChanged()
          }}
        />
      )}
    </>
  )
}

function KillSwitchDialog({
  target,
  activate,
  onClose,
  onDone,
}: {
  target: Target
  activate: boolean
  onClose: () => void
  onDone: () => void
}) {
  const [reason, setReason] = useState('')
  const [closePositions, setClosePositions] = useState(false)
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const { session } = useAuth()
  // Without sign-in there is no password: the release with a reason is the confirmation.
  const askPassword = !activate && !session?.local
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post<KillSwitch>('/kill-switches', {
        scope: target.scope,
        scope_id: target.scopeId,
        active: activate,
        reason,
        close_positions: activate && closePositions,
        ...(askPassword ? { password } : {}),
      })
      onDone()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const what = target.scope === 'GLOBAL' ? 'all trading' : target.label
  return (
    <Modal title={activate ? `Halt ${what}` : `Release ${what}`} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <p className="muted">
          {activate
            ? 'The forward runtime reads kill switches at every batch: no new entries are opened for this scope from the next batch on.'
            : askPassword
              ? 'Releasing lets the strategies open new trades again. Confirm with your password.'
              : 'Releasing lets the strategies open new trades again.'}
        </p>
        <label className="field">
          <span>Reason</span>
          <input value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} maxLength={500} required autoFocus />
        </label>
        {activate && (
          <label className="check">
            <input type="checkbox" checked={closePositions} onChange={(e) => setClosePositions(e.target.checked)} />
            Also close open positions
          </label>
        )}
        {askPassword && (
          <label className="field">
            <span>Your password</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
          </label>
        )}
        {error && <div className="error-box">{error}</div>}
        <div className="form-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className={`btn ${activate ? 'danger' : 'primary'}`} disabled={busy}>
            {busy ? 'Saving…' : activate ? 'Halt' : 'Release'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

export function KillSwitchList({ switches, onChanged }: { switches: KillSwitch[]; onChanged: () => void }) {
  if (!switches.length) return <p className="muted">No kill switch is active.</p>
  return (
    <ul className="switches">
      {switches.map((s) => (
        <li key={`${s.scope}:${s.scope_id}`}>
          <div>
            <Badge tone={s.active ? 'bad' : 'muted'}>{s.scope.toLowerCase()}</Badge> <strong>{s.label}</strong>
            {s.close_positions && <Badge tone="warn">close positions</Badge>}
            <div className="muted small">
              {s.reason} — {s.changed_by_username ?? s.changed_by}, {ago(s.changed_at)} ({dateTime(s.changed_at)})
            </div>
          </div>
          <KillSwitchButton
            target={{ scope: s.scope, scopeId: s.scope_id, label: s.label }}
            active={s.active}
            onChanged={onChanged}
            compact
          />
        </li>
      ))}
    </ul>
  )
}
