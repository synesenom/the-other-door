import { describe, expect, it } from 'vitest'
import type { DoctorReport } from './onboarding/reducer'
import { problems, type ProblemInput } from './problems'

const signedIn: DoctorReport = { ok: true, checks: [{ name: 'claude CLI', status: 'ok', required: true, detail: '' }, { name: 'claude login', status: 'ok', required: true, detail: '', details: { loggedIn: true } }] }
const signedOut: DoctorReport = { ok: false, checks: [{ name: 'claude CLI', status: 'ok', required: true, detail: '' }, { name: 'claude login', status: 'missing', required: true, detail: '', details: { loggedIn: false } }] }

const calm: ProblemInput = {
  doctor: signedIn,
  drive: { connected: false, account: null, last_synced: null, last_error: null, configured: true },
  cv: { exists: true },
  recurring: false,
}

describe('problems', () => {
  it('nothing wrong: nothing said, and a Drive that is simply off is not a problem', () => {
    expect(problems(calm)).toEqual([])
  })

  it('Claude, the CV, then Drive, each with where it is fixed', () => {
    const all = problems({
      doctor: signedOut,
      cv: { exists: false },
      drive: { ...calm.drive!, connected: true, last_error: 'offline' },
      recurring: true,
    })
    expect(all).toEqual([
      { key: 'claude', text: 'Claude is not signed in', target: 'settings' },
      { key: 'cv', text: 'You have no CV yet', target: 'profile-cv' },
      { key: 'drive', text: 'Google Drive sync failed', target: 'settings' },
      { key: 'report', text: 'Something keeps going wrong. Send a report', target: 'settings-report' },
    ])
  })

  it('a Drive conflict asks for a choice, in place of a failed sync', () => {
    const drive = { ...calm.drive!, connected: true, last_error: 'offline' }
    expect(problems({ ...calm, drive, driveConflict: true })).toEqual([{ key: 'drive', text: 'Google Drive needs a choice', target: 'settings' }])
  })

  it('no CV, no claude', () => {
    const noClaude: DoctorReport = { ok: false, checks: [{ name: 'claude CLI', status: 'missing', required: true, detail: '' }] }
    expect(problems({ ...calm, doctor: noClaude })[0]!.text).toBe('Claude is not installed')
    expect(problems({ ...calm, cv: { exists: false } })[0]!.text).toBe('You have no CV yet')
  })

  it('says nothing while it does not know', () => {
    expect(problems({ doctor: null, drive: null, cv: null, recurring: null })).toEqual([])
  })

  it('something that keeps going wrong: one line, to Report a problem; a one-off says nothing', () => {
    expect(problems({ ...calm, recurring: true })).toEqual([{ key: 'report', text: 'Something keeps going wrong. Send a report', target: 'settings-report' }])
    expect(problems({ ...calm, recurring: false })).toEqual([])
  })
})
