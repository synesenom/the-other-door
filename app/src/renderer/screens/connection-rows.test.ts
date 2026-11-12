import { describe, expect, it } from 'vitest'
import { attention, claudeRow, driveRow, type DriveStatus } from './connection-rows'
import type { DoctorReport } from './onboarding/reducer'

const cli = (ok: boolean) => ({ name: 'claude CLI', status: ok ? 'ok' : 'missing', required: true, detail: '' })
const login = (status: string, details: Record<string, unknown>) => ({ name: 'claude login', status, required: true, detail: '', details })
const report = (...checks: DoctorReport['checks']): DoctorReport => ({ ok: true, checks })

describe('claudeRow', () => {
  it('is checking while doctor has not answered', () => {
    expect(claudeRow(null)).toEqual({ kind: 'checking' })
  })

  it('signed in: as whom, on which plan', () => {
    const r = claudeRow(report(cli(true), login('ok', { loggedIn: true, email: 'ada@example.com', subscriptionType: 'max' })))
    expect(r).toEqual({ kind: 'signed-in', email: 'ada@example.com', plan: 'Max' })
  })

  it('signed out', () => {
    expect(claudeRow(report(cli(true), login('missing', { loggedIn: false }))).kind).toBe('signed-out')
  })

  it('an API key is not a plan', () => {
    expect(claudeRow(report(cli(true), login('missing', { loggedIn: true, authMethod: 'api_key' }))).kind).toBe('api-key')
  })

  it('no command line: not installed, whatever else', () => {
    expect(claudeRow(report(cli(false))).kind).toBe('not-installed')
  })

  it('a login doctor could not read is unknown, not signed out', () => {
    expect(claudeRow(report(cli(true), { name: 'claude login', status: 'warn', required: false, detail: 'could not read' })).kind).toBe('unknown')
    expect(claudeRow({ ok: false, checks: [] }).kind).toBe('unknown')
    expect(claudeRow({ matches: [] } as unknown as DoctorReport).kind).toBe('unknown')
  })

  it('doctor itself failing is unknown', () => {
    expect(claudeRow({ ok: false, checks: [], error: 'doctor could not run: the profile is locked' })).toEqual({ kind: 'unknown' })
  })
})

const off: DriveStatus = { connected: false, account: null, last_synced: null, last_error: null, configured: true }

describe('driveRow', () => {
  it('the demo and the sandbox never reach Drive', () => {
    expect(driveRow(off, 'demo')).toEqual({ kind: 'unavailable', why: 'Not available in the demo' })
    expect(driveRow(off, 'sandbox')).toEqual({ kind: 'unavailable', why: 'Not available in the onboarding sandbox' })
  })

  it('a build without the Google client cannot connect', () => {
    expect(driveRow({ ...off, configured: false }, 'real')).toEqual({ kind: 'unavailable', why: 'Not available in this build' })
  })

  it('off, connected, connected with an error', () => {
    expect(driveRow(off, 'real')).toEqual({ kind: 'off' })
    const on = { ...off, connected: true, account: 'ada@gmail.com', last_synced: '2026-10-29T08:00:00+00:00' }
    expect(driveRow(on, 'real')).toEqual({ kind: 'connected', account: 'ada@gmail.com', lastSynced: '2026-10-29T08:00:00+00:00', error: null })
    expect(driveRow({ ...on, last_error: 'offline' }, 'real')).toMatchObject({ kind: 'connected', error: 'offline' })
  })

  it('no summary yet is checking', () => {
    expect(driveRow(null, 'real')).toEqual({ kind: 'checking' })
  })
})

describe('attention', () => {
  const signedIn = report(cli(true), login('ok', { loggedIn: true }))
  it('only a Claude that is not signed in, or a Drive sync that failed', () => {
    expect(attention(signedIn, off)).toBeNull()
    expect(attention(report(cli(true), login('missing', { loggedIn: false })), off)).toBe('Claude is not signed in')
    expect(attention(report(cli(false)), off)).toBe('Claude is not installed')
    expect(attention(signedIn, { ...off, connected: true, last_error: 'offline' })).toBe('Drive sync failed')
  })

  it('says nothing while it does not know, or for a Drive that is simply off', () => {
    expect(attention(null, null)).toBeNull()
    expect(attention({ ok: false, checks: [] }, { ...off, configured: false })).toBeNull()
  })
})
