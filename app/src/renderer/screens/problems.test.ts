import { describe, expect, it } from 'vitest'
import type { DoctorReport } from './onboarding/reducer'
import type { PlanBlock } from '../api'
import { planLine, problems, type ProblemInput } from './problems'

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

  it('data that could not be upgraded comes first, to Report a problem', () => {
    const failed: DoctorReport = { ...signedOut, data: { state: 'failed', message: 'Your data could not be upgraded to this version: x. Nothing was changed. Send a report from Settings.' } }
    expect(problems({ ...calm, doctor: failed, cv: { exists: false } })).toEqual([
      { key: 'data', text: 'Your data could not be upgraded. Send a report', target: 'settings-report' },
      { key: 'claude', text: 'Claude is not signed in', target: 'settings' },
      { key: 'cv', text: 'You have no CV yet', target: 'profile-cv' },
    ])
  })

  it('data written by a newer version says to install it', () => {
    const newer: DoctorReport = { ...signedIn, data: { state: 'newer', message: 'This data was written by a newer version of The other door. Install the latest version.' } }
    expect(problems({ ...calm, doctor: newer })).toEqual([{ key: 'data', text: 'Install the latest version of The other door', target: 'settings' }])
  })

  it('data of an older major version says it cannot be opened', () => {
    const old: DoctorReport = { ...signedIn, data: { state: 'old_major', message: 'This data was written by The other door 0.x. Version 1 cannot open it: keep using 0.x, or start a new profile.' } }
    expect(problems({ ...calm, doctor: old })).toEqual([{ key: 'data', text: 'Your data is from an older version of The other door', target: 'settings' }])
  })

  it('data that is fine, or busy for a moment, says nothing', () => {
    expect(problems({ ...calm, doctor: { ...signedIn, data: { state: 'ok', message: '' } } })).toEqual([])
    expect(problems({ ...calm, doctor: { ...signedIn, data: { state: 'busy', message: 'a run is in progress' } } })).toEqual([])
  })
})

describe('the plan line', () => {
  const now = new Date(2026, 10, 14, 10, 0, 0)
  const at = (d: Date) => d.toISOString()
  const today = at(new Date(2026, 10, 14, 15, 30, 0))
  const other = at(new Date(2026, 10, 16, 9, 5, 0)) // a Monday? checked below by the weekday name
  const day = new Date(2026, 10, 16).toLocaleDateString('en-US', { weekday: 'short' })
  const plan = (over: Partial<PlanBlock> = {}): PlanBlock => ({
    as_of: at(now),
    status: 'allowed',
    five_hour: { used: 0.4, resets_at: today },
    room: { find: 6, prepare: 2 },
    binding: 'five_hour',
    ...over,
  })

  it('a limit that is reached says so, with the reset', () => {
    expect(planLine(plan({ status: 'rejected', room: { find: 0, prepare: 0 }, warning: "Claude's usage limit is reached" }), now)).toBe("Claude's usage limit is reached, resets 15:30")
    expect(planLine(plan({ status: 'rejected', room: null }), now)).toBe("Claude's usage limit is reached, resets 15:30")
  })

  it('room for three or fewer says how many, singular for one', () => {
    expect(planLine(plan(), now)).toBe('Room for about 2 more applications this window, resets 15:30')
    expect(planLine(plan({ room: { find: 1, prepare: 1 } }), now)).toBe('Room for about 1 more application this window, resets 15:30')
  })

  it('a warning shows the room too, even above three', () => {
    expect(planLine(plan({ warning: "Claude's usage limit is close", room: { find: 9, prepare: 10 } }), now)).toBe('Room for about 10 more applications this window, resets 15:30')
  })

  it('room above three and no warning: nothing', () => {
    expect(planLine(plan({ room: { find: 9, prepare: 4 } }), now)).toBeNull()
  })

  it('no plan, or no room and no warning: nothing; a warning without room is the warning', () => {
    expect(planLine(null, now)).toBeNull()
    expect(planLine(undefined, now)).toBeNull()
    expect(planLine(plan({ room: null }), now)).toBeNull()
    expect(planLine(plan({ room: null, warning: "Claude's usage limit is close" }), now)).toBe("Claude's usage limit is close, resets 15:30")
  })

  it('a window whose reset has passed says nothing, as usage.latest drops it', () => {
    const past = at(new Date(2026, 10, 14, 9, 0, 0))
    expect(planLine(plan({ five_hour: { used: 0.9, resets_at: past } }), now)).toBeNull()
    expect(planLine(plan({ five_hour: { used: 0.9, resets_at: at(now) } }), now)).toBeNull()
    expect(planLine(plan({ status: 'rejected', five_hour: { resets_at: past } }), now)).toBeNull()
  })

  it('no room at all, still allowed: says 0', () => {
    expect(planLine(plan({ room: { find: 0, prepare: 0 } }), now)).toBe('Room for about 0 more applications this window, resets 15:30')
  })

  it('no reset known: no resets part', () => {
    expect(planLine(plan({ five_hour: { used: 0.4 } }), now)).toBe('Room for about 2 more applications this window')
  })

  it('the binding window gives the reset, else the first with figures', () => {
    const both = { five_hour: { used: 0.1, resets_at: today }, seven_day: { used: 0.9, resets_at: other } }
    expect(planLine(plan({ ...both, binding: 'seven_day' }), now)).toBe(`Room for about 2 more applications this window, resets ${day} 09:05`)
    expect(planLine(plan({ ...both, binding: null }), now)).toBe('Room for about 2 more applications this window, resets 15:30')
    expect(planLine(plan({ five_hour: undefined, seven_day: { used: 0.9, resets_at: other }, binding: null }), now)).toBe(`Room for about 2 more applications this window, resets ${day} 09:05`)
  })

  it('sits after Claude and before the CV, and opens nothing', () => {
    const lines = problems({ ...calm, doctor: signedOut, cv: { exists: false }, plan: plan(), now })
    expect(lines.map((l) => l.key)).toEqual(['claude', 'plan', 'cv'])
    expect(lines[1]).toEqual({ key: 'plan', text: 'Room for about 2 more applications this window, resets 15:30', target: 'none' })
    expect(problems({ ...calm, plan: plan({ room: { find: 9, prepare: 9 } }), now })).toEqual([])
  })
})
