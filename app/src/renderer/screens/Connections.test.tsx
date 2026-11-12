// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../testing'
import { Connections } from './Connections'
import type { DriveStatus, Where } from './connection-rows'
import type { DoctorReport } from './onboarding/reducer'

/** The calls a test is about: the phone row's status read (issue 444) happens on every open. */
const calls = (call: { mock: { calls: unknown[][] } }) => call.mock.calls.filter((c) => c[0] !== 'phone_status')

afterEach(cleanup)

const cli = (ok = true) => ({ name: 'claude CLI', status: ok ? 'ok' : 'missing', required: true, detail: '' })
const signedIn: DoctorReport = { ok: true, checks: [cli(), { name: 'claude login', status: 'ok', required: true, detail: '', details: { loggedIn: true, email: 'ada@example.com', subscriptionType: 'max' } }] }
const signedOut: DoctorReport = { ok: false, checks: [cli(), { name: 'claude login', status: 'missing', required: true, detail: '', details: { loggedIn: false } }] }
const off: DriveStatus = { connected: false, account: null, last_synced: null, last_error: null, configured: true }
const on: DriveStatus = { connected: true, account: 'ada@gmail.com', last_synced: '2026-10-29T08:00:00+00:00', last_error: null, configured: true }

function show(opts: { doctor?: DoctorReport | null; drive?: DriveStatus | null; where?: Where; handlers?: Record<string, unknown>; conflict?: boolean } = {}) {
  const h = mockDoor(opts.handlers ?? {})
  const onRecheck = vi.fn()
  const onDriveChanged = vi.fn()
  const onDataChanged = vi.fn()
  const onDriveConflict = vi.fn()
  // the conflict is the app's: held here as App holds it
  function Harness() {
    const [conflict, setConflict] = useState(Boolean(opts.conflict))
    return (
      <Connections
        doctor={opts.doctor === undefined ? signedIn : opts.doctor}
        drive={opts.drive === undefined ? off : opts.drive}
        where={opts.where ?? 'real'}
        email="ada@example.com"
        onRecheck={onRecheck}
        driveConflict={conflict}
        onDriveConflict={(c) => {
          onDriveConflict(c)
          setConflict(c)
        }}
        onDriveChanged={onDriveChanged}
        onDataChanged={onDataChanged}
      />
    )
  }
  render(<Harness />)
  const row = (name: string) => within(screen.getByRole('listitem', { name }))
  return { ...h, onRecheck, onDriveChanged, onDataChanged, onDriveConflict, row }
}

describe('Connections: Claude', () => {
  it('signed in: who, the plan, no Check again, and Use another account behind a click', async () => {
    const { row, claudeLogin } = show()
    expect(row('Claude').getByText('Signed in as ada@example.com (Max)')).toBeInTheDocument()
    expect(row('Claude').queryByRole('button', { name: 'Check again' })).toBeNull()
    expect(row('Claude').queryByRole('button', { name: 'Sign in with Claude' })).toBeNull()
    await userEvent.click(row('Claude').getByRole('button', { name: 'Use another account' }))
    await userEvent.click(row('Claude').getByRole('button', { name: 'Sign in with Claude' }))
    expect(claudeLogin.start).toHaveBeenCalledWith('ada@example.com')
  })

  it('signed out: says why it matters and offers the sign-in at once', () => {
    const { row } = show({ doctor: signedOut })
    expect(row('Claude').getByText(/Not signed in\. .*needs your Claude plan/)).toBeInTheDocument()
    expect(row('Claude').getByRole('button', { name: 'Sign in with Claude' })).toBeInTheDocument()
  })

  it('not installed: Install asks first, then runs setup for claude only', async () => {
    const { row, call, onRecheck } = show({ doctor: { ok: false, checks: [cli(false)] }, handlers: { setup: { outcome: 'ok' } } })
    expect(row('Claude').getByText('Not installed')).toBeInTheDocument()
    await userEvent.click(row('Claude').getByRole('button', { name: 'Install' }))
    expect(calls(call)).toEqual([])
    await userEvent.click(screen.getByRole('button', { name: 'Install the Claude command line' }))
    expect(call).toHaveBeenCalledWith('setup', { install: ['claude'], yes: true })
    expect(onRecheck).toHaveBeenCalled()
  })

  it('Cancel or Escape on the install question installs nothing; a setup that cannot run says why', async () => {
    const { row, call } = show({
      doctor: { ok: false, checks: [cli(false)] },
      handlers: {
        setup: () => {
          throw { message: 'setup is not available' }
        },
      },
    })
    await userEvent.click(row('Claude').getByRole('button', { name: 'Install' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    await userEvent.click(row('Claude').getByRole('button', { name: 'Install' }))
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(calls(call)).toEqual([])
    await userEvent.click(row('Claude').getByRole('button', { name: 'Install' }))
    await userEvent.click(screen.getByRole('button', { name: 'Install the Claude command line' }))
    expect(await row('Claude').findByRole('alert')).toHaveTextContent('setup is not available')
  })

  it('an install that fails says why, with the installer’s own error', async () => {
    const { row } = show({
      doctor: { ok: false, checks: [cli(false)] },
      handlers: { setup: { outcome: 'incomplete', results: [{ tool: 'claude', ok: false, error: 'curl: (7) Failed to connect' }], todo: [] } },
    })
    await userEvent.click(row('Claude').getByRole('button', { name: 'Install' }))
    await userEvent.click(screen.getByRole('button', { name: 'Install the Claude command line' }))
    expect(await row('Claude').findByRole('alert')).toHaveTextContent('curl: (7) Failed to connect')
  })

  it('an install that worked says nothing failed, though the sign-in is still missing', async () => {
    const { row, onRecheck } = show({
      doctor: { ok: false, checks: [cli(false)] },
      handlers: { setup: { outcome: 'incomplete', results: [{ tool: 'claude', ok: true }], todo: [] } },
    })
    await userEvent.click(row('Claude').getByRole('button', { name: 'Install' }))
    await userEvent.click(screen.getByRole('button', { name: 'Install the Claude command line' }))
    await waitFor(() => expect(onRecheck).toHaveBeenCalled())
    expect(row('Claude').queryByRole('alert')).toBeNull()
  })

  it('doctor failing: cannot read the sign-in, with Check again', () => {
    const { row } = show({ doctor: { ok: false, checks: [], error: 'doctor could not run: the profile is locked' } })
    expect(row('Claude').getByText(/could not read the Claude sign-in/)).toBeInTheDocument()
    expect(row('Claude').getByRole('button', { name: 'Check again' })).toBeInTheDocument()
  })

  it('Use another account closes once the sign-in is done and doctor has answered', async () => {
    const { row, pushLogin, onRecheck } = show()
    await userEvent.click(row('Claude').getByRole('button', { name: 'Use another account' }))
    await act(async () => pushLogin({ state: 'done' }))
    expect(onRecheck).toHaveBeenCalled()
    expect(row('Claude').queryByRole('status')).toBeNull()
    expect(row('Claude').getByRole('button', { name: 'Use another account' })).toBeInTheDocument()
  })

  it('checking while doctor has not answered', () => {
    const { row } = show({ doctor: null })
    expect(row('Claude').getByRole('status')).toHaveTextContent('Checking')
  })
})

describe('Connections: Google Drive', () => {
  it('nothing runs when the list opens', () => {
    const { call, claudeLogin } = show({ drive: on })
    expect(call.mock.calls.map((c) => c[0])).toEqual([])
    expect(claudeLogin.start).not.toHaveBeenCalled()
  })

  it('off: what it is for; Connect connects, then syncs at once and says what it did', async () => {
    const { row, call, onDriveChanged, onDataChanged } = show({ handlers: { connect_drive: { account: 'ada@gmail.com' }, sync_data: { action: 'push', version: 'v1' } } })
    expect(row('Google Drive').getByText('Keeps this computer and another one in step.')).toBeInTheDocument()
    await userEvent.click(row('Google Drive').getByRole('button', { name: 'Connect' }))
    expect(calls(call)).toEqual([
      ['connect_drive', {}],
      ['sync_data', {}],
    ])
    expect(row('Google Drive').getByText("Sent this computer's data to Drive.")).toBeInTheDocument()
    expect(row('Google Drive').queryByText(/Connected as/)).toBeNull()
    expect(onDriveChanged).toHaveBeenCalled()
    expect(onDataChanged).not.toHaveBeenCalled()
  })

  it("connecting to a Drive that already has data brings it here and reloads", async () => {
    const { row, onDataChanged } = show({ handlers: { connect_drive: { account: 'ada@gmail.com' }, sync_data: { action: 'pull', version: 'v2' } } })
    await userEvent.click(row('Google Drive').getByRole('button', { name: 'Connect' }))
    expect(row('Google Drive').getByText("Brought Drive's data to this computer.")).toBeInTheDocument()
    expect(onDataChanged).toHaveBeenCalled()
  })

  it('a failed connect says why', async () => {
    const { row } = show({
      handlers: {
        connect_drive: () => {
          throw { message: 'access denied' }
        },
      },
    })
    await userEvent.click(row('Google Drive').getByRole('button', { name: 'Connect' }))
    expect(row('Google Drive').getByRole('alert')).toHaveTextContent('access denied')
  })

  it('connected: the account, the last sync and its error, and only Disconnect', async () => {
    const { row } = show({ drive: { ...on, last_error: 'Google Drive is unreachable' } })
    expect(row('Google Drive').getByText(/^ada@gmail\.com · last synced /)).toBeInTheDocument()
    expect(row('Google Drive').getByText('The last sync failed: Google Drive is unreachable')).toBeInTheDocument()
    expect(row('Google Drive').getAllByRole('button').map((b) => b.textContent)).toEqual(['Disconnect'])
  })

  it('both changed (found on opening): the two choices in words; Keep this computer sends it', async () => {
    const { row, call, onDataChanged, onDriveConflict } = show({ drive: on, conflict: true, handlers: { sync_data: { action: 'push', version: 'v3' } } })
    expect(row('Google Drive').getByText('This computer and Drive both changed since they last synced. Nothing was replaced.')).toBeInTheDocument()
    expect(row('Google Drive').getByText(/replaces the copy on Drive/)).toBeInTheDocument()
    expect(row('Google Drive').getByText(/which is kept as a backup\.$/)).toBeInTheDocument()
    expect(row('Google Drive').queryByRole('button', { name: 'Disconnect' })).toBeNull()
    expect(calls(call)).toEqual([])
    await userEvent.click(row('Google Drive').getByRole('button', { name: 'Keep this computer' }))
    expect(calls(call)).toEqual([['sync_data', { keep_local: true }]])
    expect(onDriveConflict).toHaveBeenCalledWith(false)
    expect(row('Google Drive').getByText("Sent this computer's data to Drive.")).toBeInTheDocument()
    expect(onDataChanged).not.toHaveBeenCalled()
  })

  it('Keep Drive brings it here and reloads; Not now puts the choice away', async () => {
    const { row, call, onDataChanged } = show({ drive: on, conflict: true, handlers: { sync_data: { action: 'pull' } } })
    await userEvent.click(row('Google Drive').getByRole('button', { name: 'Keep Drive' }))
    expect(call).toHaveBeenLastCalledWith('sync_data', { keep_drive: true })
    expect(onDataChanged).toHaveBeenCalled()
    cleanup()
    const again = show({ drive: on, conflict: true })
    await userEvent.click(again.row('Google Drive').getByRole('button', { name: 'Not now' }))
    expect(again.row('Google Drive').queryByText(/both changed/)).toBeNull()
    expect(again.onDriveConflict).toHaveBeenCalledWith(false)
  })

  it('a connect that finds both sides changed asks which to keep', async () => {
    const { row, onDriveConflict } = show({
      handlers: {
        connect_drive: { account: 'ada@gmail.com' },
        sync_data: () => {
          throw { message: 'both changed', conflict: true }
        },
      },
    })
    await userEvent.click(row('Google Drive').getByRole('button', { name: 'Connect' }))
    expect(onDriveConflict).toHaveBeenCalledWith(true) // the row, connected once the status is read again, asks
    expect(row('Google Drive').queryByRole('alert')).toBeNull()
  })

  it('Disconnect asks first, then sends the last changes and disconnects', async () => {
    const { row, call, onDriveChanged } = show({ drive: on, handlers: { sync_data: { action: 'push' }, disconnect_drive: { disconnected: true } } })
    await userEvent.click(row('Google Drive').getByRole('button', { name: 'Disconnect' }))
    expect(calls(call)).toEqual([])
    expect(screen.getByRole('dialog')).toHaveTextContent('The last changes go to Drive first')
    expect(screen.getByRole('dialog')).toHaveTextContent('The copy on Drive stays')
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Disconnect' }))
    expect(calls(call)).toEqual([
      ['sync_data', {}],
      ['disconnect_drive', {}],
    ])
    expect(row('Google Drive').getByText('Disconnected. The copy on Drive stays.')).toBeInTheDocument()
    expect(onDriveChanged).toHaveBeenCalled()
  })

  it('a last sync that fails does not keep Drive connected: it disconnects and says the changes did not reach Drive', async () => {
    const { row, call } = show({
      drive: on,
      handlers: {
        sync_data: () => {
          throw { message: 'Google Drive is unreachable' }
        },
        disconnect_drive: { disconnected: true },
      },
    })
    await userEvent.click(row('Google Drive').getByRole('button', { name: 'Disconnect' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Disconnect' }))
    expect(call).toHaveBeenCalledWith('disconnect_drive', {})
    expect(row('Google Drive').getByText('Disconnected. The last changes did not reach Drive: Google Drive is unreachable')).toBeInTheDocument()
  })

  it('a last sync that finds both sides changed stops the disconnect and asks which to keep', async () => {
    const { row, call } = show({
      drive: on,
      handlers: {
        sync_data: () => {
          throw { message: 'both changed', conflict: true }
        },
      },
    })
    await userEvent.click(row('Google Drive').getByRole('button', { name: 'Disconnect' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Disconnect' }))
    expect(call).not.toHaveBeenCalledWith('disconnect_drive', {})
    expect(row('Google Drive').getByText(/both changed since they last synced/)).toBeInTheDocument()
  })

  it('the demo and the sandbox say Drive is not available, and offer nothing', () => {
    for (const where of ['demo', 'sandbox'] as const) {
      const { row } = show({ where })
      expect(row('Google Drive').getByText(/Not available in the (demo|onboarding sandbox)/)).toBeInTheDocument()
      expect(row('Google Drive').queryAllByRole('button')).toHaveLength(0)
      cleanup()
    }
  })

  it('a build without the Google client says so', () => {
    const { row } = show({ drive: { ...off, configured: false } })
    expect(row('Google Drive').getByText('Not available in this build')).toBeInTheDocument()
    expect(row('Google Drive').queryAllByRole('button')).toHaveLength(0)
  })
})
