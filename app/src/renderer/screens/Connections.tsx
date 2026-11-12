import { AppName, named } from './AppName'
import { CheckMark } from './CheckMark'
import { PhoneSetup, type PhoneStatus } from './PhoneSetup'
import { useEffect, useState, type ReactNode } from 'react'
import { ApiError, call, errorText } from '../api'
import { claudeRow, driveRow, installFailure, type DriveStatus, type SetupAnswer, type Where } from './connection-rows'
import { Dialog } from './Dialog'
import type { DoctorReport } from './onboarding/reducer'
import { SignIn } from './SignIn'
import { Spinner } from './Spinner'

/** "Oct 29, 09:00", or null when the time is unreadable. */
function when(iso: string | null): string | null {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

/**
 * One connection: its name and the state in words (a green circle with a check when fine, a quiet ring when not),
 * its everyday buttons on the right; a flow that takes more room (a sign-in, a conflict, an error) goes under the state.
 */
function Row({ name, fine, state, actions, children }: { name: string; fine: boolean; state: ReactNode; actions?: ReactNode; children?: ReactNode }) {
  const id = `connection-${name.replace(/\s+/g, '-').toLowerCase()}`
  return (
    <li className="connection" aria-labelledby={id}>
      <span className={fine ? 'connection-mark connection-fine' : 'connection-mark'} aria-hidden="true">
        {fine ? <CheckMark /> : ''}
      </span>
      <div className="connection-body">
        <h3 className="body item-name" id={id}>
          {name}
        </h3>
        {state}
        {children}
      </div>
      {actions && <div className="actions connection-actions">{actions}</div>}
    </li>
  )
}

function ClaudeConnection({ doctor, email, onRecheck }: { doctor: DoctorReport | null; email?: string; onRecheck: () => void | Promise<void> }) {
  const row = claudeRow(doctor)
  const [again, setAgain] = useState(false)
  const [asking, setAsking] = useState(false)
  const [installing, setInstalling] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const install = async () => {
    setAsking(false)
    setInstalling(true)
    setError(null)
    try {
      const r = await call<SetupAnswer>('setup', { install: ['claude'], yes: true })
      setError(installFailure(r))
      void onRecheck()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setInstalling(false)
    }
  }

  const fine = row.kind === 'signed-in'
  let state: ReactNode
  let body: ReactNode = null
  let actions: ReactNode = null
  if (row.kind === 'checking') state = <Spinner message="Checking Claude…" />
  else if (row.kind === 'signed-in') {
    const who = row.email ? `Signed in as ${row.email}` : 'Signed in'
    state = <p className="small muted">{row.plan ? `${who} (${row.plan})` : who}</p>
    // no Check again: opening Settings reads doctor again, and a signed-in row has nothing to fix
    actions = !again && (
      <button type="button" className="secondary" onClick={() => setAgain(true)}>
        Use another account
      </button>
    )
    body = (
      <>
        {again && (
          <SignIn
            email={email}
            onDone={async () => {
              await onRecheck()
              setAgain(false) // done with: still signed in shows the row, signed out its own sign-in
            }}
          />
        )}
      </>
    )
  } else if (row.kind === 'not-installed') {
    state = <p className="small muted">Not installed</p>
    if (installing) body = <Spinner message="Installing the Claude command line…" />
    else
      actions = (
        <button type="button" className="secondary" onClick={() => setAsking(true)}>
          Install
        </button>
      )
  } else if (row.kind === 'unknown') {
    state = <p className="small muted"><AppName /> could not read the Claude sign-in.</p>
    actions = (
      <button type="button" className="secondary" onClick={() => void onRecheck()}>
        Check again
      </button>
    )
  } else {
    state = (
      <p className="body">
        {row.kind === 'api-key' ? (
          <>Signed in with an API key. <AppName /> runs on a Pro or Max plan, never an API key.</>
        ) : (
          <>Not signed in. <AppName /> needs your Claude plan to score jobs and write applications.</>
        )}
      </p>
    )
    body = <SignIn email={email} onDone={onRecheck} />
  }
  return (
    <Row name="Claude" fine={fine} state={state} actions={actions}>
      {body}
      {error && (
        <p role="alert" className="small error">
          {named(error)}
        </p>
      )}
      {asking && (
        <Dialog title="Install the Claude command line?" onClose={() => setAsking(false)}>
          <p className="body">It is installed for you only, without asking for a password.</p>
          <div className="actions">
            <button type="button" className="quiet" onClick={() => setAsking(false)}>
              Cancel
            </button>
            <button type="button" className="primary" onClick={() => void install()}>
              Install the Claude command line
            </button>
          </div>
        </Dialog>
      )}
    </Row>
  )
}

const SYNCED: Record<string, string> = {
  push: "Sent this computer's data to Drive.",
  pull: "Brought Drive's data to this computer.",
  nothing: 'Already in step.',
  skipped: 'Nothing to send yet.',
}

/** What a sync answers. */
type Synced = { action: string }

/**
 * Google Drive: no Sync now. It syncs by itself: on connecting, when the app opens (App), around every change
 * of the data (the server's lock hooks) and before disconnecting. Only a conflict, both sides changed, needs
 * the user: it is the app's (`conflict`), so a sync on opening can ask here and in the sidebar.
 */
function DriveConnection({
  drive,
  where,
  conflict,
  onConflict,
  onDriveChanged,
  onDataChanged,
}: {
  drive: DriveStatus | null
  where: Where
  conflict: boolean
  onConflict: (conflict: boolean) => void
  onDriveChanged: () => void
  onDataChanged: () => void
}) {
  const row = driveRow(drive, where)
  const [busy, setBusy] = useState<null | 'connect' | 'sync' | 'disconnect'>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const syncData = async (choice: Record<string, true> = {}): Promise<Synced> => {
    const r = await call<Synced>('sync_data', choice)
    if (r.action === 'pull') onDataChanged()
    return r
  }

  const act = async (what: 'connect' | 'sync' | 'disconnect', run: () => Promise<string | null>) => {
    setBusy(what)
    setMessage(null)
    setError(null)
    try {
      setMessage(await run())
    } catch (e) {
      if (e instanceof ApiError && e.conflict) onConflict(true)
      else setError(errorText(e))
    } finally {
      setBusy(null)
      onDriveChanged()
    }
  }
  // connected, then in step at once: what is on Drive comes here, or this computer's data goes there
  const connect = () =>
    act('connect', async () => {
      await call('connect_drive', {})
      return SYNCED[(await syncData()).action] ?? null
    })
  // a choice of the conflict: the side to keep
  const keep = (choice: Record<string, true>) =>
    act('sync', async () => {
      onConflict(false)
      return SYNCED[(await syncData(choice)).action] ?? 'Synced.'
    })
  // the last changes go to Drive first; a conflict stops it (the choice opens), any other failure does not
  const disconnect = () => {
    setConfirming(false)
    return act('disconnect', async () => {
      let unsent: string | null = null
      try {
        await syncData()
      } catch (e) {
        if (e instanceof ApiError && e.conflict) throw e
        unsent = errorText(e)
      }
      await call('disconnect_drive', {})
      return unsent ? `Disconnected. The last changes did not reach Drive: ${unsent}` : 'Disconnected. The copy on Drive stays.'
    })
  }

  let state: ReactNode
  let body: ReactNode = null
  let actions: ReactNode = null
  if (row.kind === 'checking') state = <Spinner message="Checking Google Drive…" />
  else if (row.kind === 'unavailable') state = <p className="small muted">{row.why}</p>
  else if (row.kind === 'off') {
    state = <p className="small muted">Keeps this computer and another one in step.</p>
    if (busy === 'connect') body = <Spinner message="Waiting for you to allow access in the browser (up to five minutes), then syncing…" />
    else
      actions = (
        <button type="button" className="secondary" onClick={() => void connect()}>
          Connect
        </button>
      )
  } else {
    const last = when(row.lastSynced)
    const who = row.account ?? 'Connected'
    state = (
      <>
        <p className="small muted">{last ? `${who} · last synced ${last}` : `${who} · not synced yet`}</p>
        {row.error && <p className="small error">{`The last sync failed: ${row.error}`}</p>}
      </>
    )
    if (!busy && !conflict)
      actions = (
        <button type="button" className="secondary" onClick={() => setConfirming(true)}>
          Disconnect
        </button>
      )
    body = busy ? (
      <Spinner message={busy === 'sync' ? 'Syncing with Google Drive…' : 'Sending the last changes to Drive, then disconnecting…'} />
    ) : conflict ? (
      <div className="connection-choice">
        <p className="body">This computer and Drive both changed since they last synced. Nothing was replaced.</p>
        <ul className="small muted">
          <li>Keep this computer: its data replaces the copy on Drive.</li>
          <li>Keep Drive: Drive's data replaces this computer's, which is kept as a backup.</li>
        </ul>
        <div className="actions">
          <button type="button" className="secondary" onClick={() => void keep({ keep_local: true })}>
            Keep this computer
          </button>
          <button type="button" className="secondary" onClick={() => void keep({ keep_drive: true })}>
            Keep Drive
          </button>
          <button type="button" className="quiet" onClick={() => onConflict(false)}>
            Not now
          </button>
        </div>
      </div>
    ) : null
  }
  return (
    <Row name="Google Drive" fine={row.kind === 'connected' && !row.error} state={state} actions={actions}>
      {body}
      {message && <p className="small">{message}</p>}
      {error && (
        <p role="alert" className="small error">
          {named(error)}
        </p>
      )}
      {confirming && (
        <Dialog title="Disconnect Google Drive?" onClose={() => setConfirming(false)}>
          <p className="body">The last changes go to Drive first, then this computer stops syncing. The copy on Drive stays, and you can connect again later.</p>
          <div className="actions">
            <button type="button" className="quiet" onClick={() => setConfirming(false)}>
              Cancel
            </button>
            <button type="button" className="primary" onClick={() => void disconnect()}>
              Disconnect
            </button>
          </div>
        </Dialog>
      )}
    </Row>
  )
}

/**
 * What The other door is connected to, each with its state in words and its actions: Claude (required) and
 * Google Drive (optional). Nothing here runs by itself: doctor is read by the screen that shows it.
 */
/** Your phone (issue 444): one phone, served from this computer; the setup is a dialog. No word of serving or
 * addresses here: connected or not, and one Disconnect that undoes it all. */
export function PhoneConnection() {
  const [status, setStatus] = useState<PhoneStatus | null>(null)
  const [setup, setSetup] = useState<'how' | 'pair' | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const load = async () => {
    try {
      setStatus(await call<PhoneStatus>('phone_status'))
      setError(null)
    } catch (e) {
      setError(errorText(e))
    }
  }
  useEffect(() => {
    void load()
  }, [])
  // Disconnect: the phone's pairing goes (every one this computer keeps: one, or an old second from before),
  // then this computer stops serving it
  const disconnect = () => {
    setConfirming(false)
    return run(async () => {
      for (const d of status?.devices ?? []) await call('unpair_phone', { device: d.device })
      await call('phone_stop', {})
    })
  }
  const run = async (work: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await work()
      await load()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const running = Boolean(status?.running)
  const paired = (status?.devices.length ?? 0) > 0
  let state: ReactNode
  if (status === null && !error) state = <Spinner message="Checking your phone…" />
  else if (!running && paired) state = <p className="small muted">Disconnected when this computer restarted. Set it up again and scan a new code.</p>
  // not set up: the name and Set up your phone say it all, and the dialog tells what it is
  else if (!running) state = null
  else if (!paired) state = <p className="small muted">Not paired yet.</p>
  else state = <p className="small muted">{status!.lasting ? 'Connected' : 'Connected until this computer restarts'}</p>
  const actions = running ? (
    <>
      <button type="button" className="secondary" disabled={busy} onClick={() => setConfirming(true)}>
        Disconnect
      </button>
      {!paired && (
        <button type="button" className="secondary" disabled={busy} onClick={() => setSetup('pair')}>
          Pair your phone
        </button>
      )}
    </>
  ) : status !== null ? (
    <button type="button" className="secondary" onClick={() => setSetup('how')}>
      Set up your phone
    </button>
  ) : error ? (
    // the state could not be read: no setup to offer yet, only another read
    <button type="button" className="secondary" onClick={() => void load()}>
      Check again
    </button>
  ) : null
  return (
    <Row name="Your phone" fine={running && paired} state={state} actions={actions}>
      {error && (
        <p role="alert" className="small error">
          {named(error)}
        </p>
      )}
      {confirming && (
        <Dialog title="Disconnect your phone?" onClose={() => setConfirming(false)}>
          <p className="body">Your phone stops reaching <AppName />. To use it again, set it up here and scan a new code.</p>
          <div className="actions">
            <button type="button" className="quiet" onClick={() => setConfirming(false)}>
              Cancel
            </button>
            <button type="button" className="primary" onClick={() => void disconnect()}>
              Disconnect
            </button>
          </div>
        </Dialog>
      )}
      {setup && (
        <PhoneSetup
          start={setup}
          onClose={() => {
            setSetup(null)
            void load()
          }}
        />
      )}
    </Row>
  )
}

export function Connections({
  doctor,
  drive,
  where,
  email,
  onRecheck,
  driveConflict = false,
  onDriveConflict = () => undefined,
  onDriveChanged,
  onDataChanged,
}: {
  doctor: DoctorReport | null
  drive: DriveStatus | null
  where: Where
  email?: string
  onRecheck: () => void | Promise<void>
  /** Both sides changed (a sync found it, here or on opening): the Drive row asks which to keep. */
  driveConflict?: boolean
  onDriveConflict?: (conflict: boolean) => void
  onDriveChanged: () => void
  onDataChanged: () => void
}) {
  return (
    <ul className="connections" aria-label="Connections">
      <ClaudeConnection doctor={doctor} email={email} onRecheck={onRecheck} />
      <DriveConnection drive={drive} where={where} conflict={driveConflict} onConflict={onDriveConflict} onDriveChanged={onDriveChanged} onDataChanged={onDataChanged} />
    </ul>
  )
}
