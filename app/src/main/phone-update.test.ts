import { afterEach, describe, expect, it, vi } from 'vitest'
import { quitStep, restorePhoneAtStart, stopForUpdate, stopPhoneForUpdate, stopStyleBuildForUpdate } from './phone-update'

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

describe('stopStyleBuildForUpdate', () => {
  it('stops a running CV style build, waiting as long as its timeout', async () => {
    const s = setup({ stop_style_build: () => ({ stopped: true }) })
    await stopStyleBuildForUpdate(s.deps)
    expect(s.call).toHaveBeenCalledWith('stop_style_build', {}, 100)
    expect(s.log).not.toHaveBeenCalled()
  })
  it('logs a failing call and resolves', async () => {
    const s = setup({
      stop_style_build: () => {
        throw new Error('boom')
      },
    })
    await stopStyleBuildForUpdate(s.deps)
    expect(s.log).toHaveBeenCalledWith(expect.stringContaining('boom'))
  })
  it('gives up on a call that hangs', async () => {
    vi.useFakeTimers()
    const s = setup({ stop_style_build: () => new Promise(() => undefined) })
    const p = stopStyleBuildForUpdate(s.deps)
    await vi.advanceTimersByTimeAsync(150)
    await p
    expect(s.log).toHaveBeenCalled()
  })
})

describe('stopForUpdate', () => {
  it('stops the style build even when stopping the phone server fails', async () => {
    const s = setup({
      phone_status: () => {
        throw new Error('phone')
      },
      stop_style_build: () => ({ stopped: true }),
    })
    await stopForUpdate(s.deps)
    expect(s.call).toHaveBeenCalledWith('stop_style_build', {}, 100)
  })
})

describe('restorePhoneAtStart: after an update', () => {
  it('starts Tailscale again and removes the marker', async () => {
    const s = setup({ phone_start: () => ({ running: true }) }, true)
    await restorePhoneAtStart(s.deps)
    expect(s.call).toHaveBeenCalledWith('phone_start', { connection: 'tailscale' }, 300_000)
    expect(s.files.has('/m')).toBe(false)
  })
  it('does nothing without a marker', async () => {
    const s = setup({ phone_status: () => ({ running: false }) })
    await restorePhoneAtStart(s.deps)
    expect(s.call).not.toHaveBeenCalledWith('phone_start', expect.anything(), expect.anything())
    expect(s.call).not.toHaveBeenCalledWith('phone_stop', {})
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
    await restorePhoneAtStart(s.deps)
    expect(s.log).toHaveBeenCalled()
    expect(s.files.has('/m')).toBe(false)
  })
  it('removes the marker before starting, so a start that never ends is not retried', async () => {
    const s = setup({ phone_start: () => new Promise(() => undefined) }, true)
    void restorePhoneAtStart(s.deps)
    await Promise.resolve()
    expect(s.files.has('/m')).toBe(false)
  })
  it('waits for a slow start as long as the window would, and logs nothing on success', async () => {
    vi.useFakeTimers()
    const s = setup({ phone_start: () => new Promise((r) => setTimeout(() => r({ running: true }), 60_000)) }, true)
    const p = restorePhoneAtStart(s.deps)
    await vi.advanceTimersByTimeAsync(60_000)
    await p
    expect(s.call).toHaveBeenCalledWith('phone_start', { connection: 'tailscale' }, 300_000)
    expect(s.log).not.toHaveBeenCalled()
  })
})

describe('quitStep', () => {
  it('lets a quit with no downloaded update proceed', () => {
    expect(quitStep({ installsOnQuit: false, stopped: false })).toBe('proceed')
  })
  it('stops the phone server and a style build first when the quit installs an update', () => {
    expect(quitStep({ installsOnQuit: true, stopped: false })).toBe('stop-then-quit')
  })
  it('proceeds once they are stopped, so quitting again does not loop', () => {
    expect(quitStep({ installsOnQuit: true, stopped: true })).toBe('proceed')
  })
})

describe('restorePhoneAtStart: an older version left a server', () => {
  const old = (connection: string) => ({ phone_status: () => ({ running: true, outdated: true, connection }), phone_stop: () => ({ stopped: true }), phone_start: () => ({ running: true }) })
  it('stops an outdated server and starts Tailscale again', async () => {
    const s = setup(old('tailscale'))
    await restorePhoneAtStart(s.deps)
    expect(s.call).toHaveBeenCalledWith('phone_start', { connection: 'tailscale' }, 300_000)
    expect(s.call).not.toHaveBeenCalledWith('phone_stop', {})
  })
  it('leaves a quick tunnel stopped', async () => {
    const s = setup(old('cloudflare'))
    await restorePhoneAtStart(s.deps)
    expect(s.call).toHaveBeenCalledWith('phone_stop', {})
    expect(s.call).not.toHaveBeenCalledWith('phone_start', expect.anything(), expect.anything())
  })
  it('leaves a current server, and a stopped one alone', async () => {
    for (const calls of [
      { phone_status: () => ({ running: true, outdated: false, connection: 'tailscale' }) },
      { phone_status: () => ({ running: false, outdated: true }) },
    ]) {
      const s = setup({ ...calls })
      await restorePhoneAtStart(s.deps)
      expect(s.call).not.toHaveBeenCalledWith('phone_stop', {})
    }
  })
  it('logs a failed restart', async () => {
    const s = setup({ ...old('tailscale'), phone_start: () => ({ error: 'nope' }) })
    await restorePhoneAtStart(s.deps)
    expect(s.log).toHaveBeenCalled()
  })
  it('acts on a first answer that is slow, as a cold start with a migration is', async () => {
    vi.useFakeTimers()
    const s = setup({ ...old('cloudflare'), phone_status: () => new Promise((r) => setTimeout(() => r({ running: true, outdated: true, connection: 'cloudflare' }), 40_000)) })
    const p = restorePhoneAtStart({ ...s.deps, timeoutMs: undefined })
    await vi.advanceTimersByTimeAsync(40_000)
    await p
    expect(s.call).toHaveBeenCalledWith('phone_stop', {})
  })
})
