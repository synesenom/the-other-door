import { afterEach, describe, expect, it, vi } from 'vitest'
import { quitStep, restorePhoneAfterUpdate, stopPhoneForUpdate } from './phone-update'

function setup(calls: Record<string, (args: any) => unknown>, marker = false) {
  const files = new Set<string>(marker ? ['/m'] : [])
  const call = vi.fn(async (tool: string, args?: Record<string, unknown>, _timeoutMs?: number) => {
    const f = calls[tool]
    if (!f) throw new Error(`no ${tool}`)
    return f(args)
  })
  const log = vi.fn()
  const fs = {
    write: vi.fn((p: string) => void files.add(p)),
    exists: (p: string) => files.has(p),
    remove: vi.fn((p: string) => void files.delete(p)),
  }
  return { call, log, fs, files, deps: { call: call as any, markerPath: '/m', fs, log, timeoutMs: 100 } }
}

afterEach(() => vi.useRealTimers())

describe('stopPhoneForUpdate', () => {
  it('stops what is left even when status says not running, and leaves no marker', async () => {
    // a quick tunnel that died reads as not running while `door serve` is still alive
    const s = setup({ phone_status: () => ({ running: false }), phone_stop: () => ({ stopped: true }) })
    await stopPhoneForUpdate(s.deps)
    expect(s.call).toHaveBeenCalledWith('phone_stop', {})
    expect(s.files.size).toBe(0)
  })
  it('leaves no marker when stopping a lasting connection fails', async () => {
    const s = setup({
      phone_status: () => ({ running: true, lasting: true }),
      phone_stop: () => {
        throw new Error('stuck')
      },
    })
    await stopPhoneForUpdate(s.deps)
    expect(s.log).toHaveBeenCalledWith(expect.stringContaining('stuck'))
    expect(s.files.size).toBe(0)
  })
  it('stops a quick tunnel and leaves no marker', async () => {
    const s = setup({ phone_status: () => ({ running: true, lasting: false }), phone_stop: () => ({}) })
    await stopPhoneForUpdate(s.deps)
    expect(s.call).toHaveBeenCalledWith('phone_stop', {})
    expect(s.files.size).toBe(0)
  })
  it('stops a lasting connection and leaves the marker', async () => {
    const s = setup({ phone_status: () => ({ running: true, lasting: true }), phone_stop: () => ({}) })
    await stopPhoneForUpdate(s.deps)
    expect(s.call).toHaveBeenCalledWith('phone_stop', {})
    expect(s.files.has('/m')).toBe(true)
  })
  it('logs a failing call and resolves', async () => {
    const s = setup({
      phone_status: () => {
        throw new Error('boom')
      },
    })
    await stopPhoneForUpdate(s.deps)
    expect(s.log).toHaveBeenCalledWith(expect.stringContaining('boom'))
  })
  it('gives up on a call that hangs', async () => {
    vi.useFakeTimers()
    const s = setup({ phone_status: () => new Promise(() => undefined) })
    const p = stopPhoneForUpdate(s.deps)
    await vi.advanceTimersByTimeAsync(150)
    await p
    expect(s.log).toHaveBeenCalled()
    expect(s.files.size).toBe(0)
  })
})

describe('restorePhoneAfterUpdate', () => {
  it('starts Tailscale again and removes the marker', async () => {
    const s = setup({ phone_start: () => ({ running: true }) }, true)
    await restorePhoneAfterUpdate(s.deps)
    expect(s.call).toHaveBeenCalledWith('phone_start', { connection: 'tailscale' }, 300_000)
    expect(s.files.has('/m')).toBe(false)
  })
  it('does nothing without a marker', async () => {
    const s = setup({})
    await restorePhoneAfterUpdate(s.deps)
    expect(s.call).not.toHaveBeenCalled()
  })
  it.each([
    ['needs', () => ({ needs: 'sign_in', link: 'x' })],
    ['error', () => ({ error: 'nope' })],
    [
      'throw',
      () => {
        throw new Error('x')
      },
    ],
  ])('logs %s and still removes the marker', async (_n, f) => {
    const s = setup({ phone_start: f }, true)
    await restorePhoneAfterUpdate(s.deps)
    expect(s.log).toHaveBeenCalled()
    expect(s.files.has('/m')).toBe(false)
  })
  it('removes the marker before starting, so a start that never ends is not retried', async () => {
    const s = setup({ phone_start: () => new Promise(() => undefined) }, true)
    void restorePhoneAfterUpdate(s.deps)
    await Promise.resolve()
    expect(s.files.has('/m')).toBe(false)
  })
  it('waits for a slow start as long as the window would, and logs nothing on success', async () => {
    vi.useFakeTimers()
    const s = setup({ phone_start: () => new Promise((r) => setTimeout(() => r({ running: true }), 60_000)) }, true)
    const p = restorePhoneAfterUpdate(s.deps)
    await vi.advanceTimersByTimeAsync(60_000)
    await p
    expect(s.call).toHaveBeenCalledWith('phone_start', { connection: 'tailscale' }, 300_000)
    expect(s.log).not.toHaveBeenCalled()
  })
})

describe('quitStep', () => {
  it('lets a quit with no downloaded update proceed', () => {
    expect(quitStep({ installsOnQuit: false, phoneStopped: false })).toBe('proceed')
  })
  it('stops the phone first when the quit installs an update', () => {
    expect(quitStep({ installsOnQuit: true, phoneStopped: false })).toBe('stop-then-quit')
  })
  it('proceeds once the phone is stopped, so quitting again does not loop', () => {
    expect(quitStep({ installsOnQuit: true, phoneStopped: true })).toBe('proceed')
  })
})
