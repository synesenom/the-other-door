import { afterEach, describe, expect, it, vi } from 'vitest'
import { quitStep, stopOutdatedPhoneAtStart, stopPhoneForUpdate } from './phone-update'

function setup(calls: Record<string, (args: any) => unknown>) {
  const call = vi.fn(async (tool: string, args?: Record<string, unknown>, _timeoutMs?: number) => {
    const f = calls[tool]
    if (!f) throw new Error(`no ${tool}`)
    return f(args)
  })
  const log = vi.fn()
  return { call, log, deps: { call: call as any, log, timeoutMs: 100 } }
}

afterEach(() => vi.useRealTimers())

describe('stopPhoneForUpdate', () => {
  it('stops the server without asking its status first, as a dead tunnel reads as not running', async () => {
    const s = setup({ phone_stop: () => ({ stopped: true }) })
    await stopPhoneForUpdate(s.deps)
    expect(s.call).toHaveBeenCalledWith('phone_stop', {})
    expect(s.call).not.toHaveBeenCalledWith('phone_start', expect.anything(), expect.anything())
  })
  it('logs a failing call and resolves', async () => {
    const s = setup({
      phone_stop: () => {
        throw new Error('boom')
      },
    })
    await stopPhoneForUpdate(s.deps)
    expect(s.log).toHaveBeenCalledWith(expect.stringContaining('boom'))
  })
  it('gives up on a call that hangs', async () => {
    vi.useFakeTimers()
    const s = setup({ phone_stop: () => new Promise(() => undefined) })
    const p = stopPhoneForUpdate(s.deps)
    await vi.advanceTimersByTimeAsync(150)
    await p
    expect(s.log).toHaveBeenCalled()
  })
})

describe('quitStep', () => {
  it('lets a quit with no downloaded update proceed', () => {
    expect(quitStep({ installsOnQuit: false, stopped: false })).toBe('proceed')
  })
  it('stops the phone server first when the quit installs an update', () => {
    expect(quitStep({ installsOnQuit: true, stopped: false })).toBe('stop-then-quit')
  })
  it('proceeds once they are stopped, so quitting again does not loop', () => {
    expect(quitStep({ installsOnQuit: true, stopped: true })).toBe('proceed')
  })
})

describe('stopOutdatedPhoneAtStart', () => {
  it('stops a server an older version left and starts nothing', async () => {
    const s = setup({ phone_status: () => ({ running: true, outdated: true }), phone_stop: () => ({ stopped: true }) })
    await stopOutdatedPhoneAtStart(s.deps)
    expect(s.call).toHaveBeenCalledWith('phone_stop', {})
    expect(s.call).not.toHaveBeenCalledWith('phone_start', expect.anything(), expect.anything())
  })
  it('leaves a current server, and a stopped one alone', async () => {
    for (const status of [{ running: true, outdated: false }, { running: false, outdated: true }]) {
      const s = setup({ phone_status: () => status })
      await stopOutdatedPhoneAtStart(s.deps)
      expect(s.call).not.toHaveBeenCalledWith('phone_stop', {})
    }
  })
  it('logs a failed stop', async () => {
    const s = setup({
      phone_status: () => ({ running: true, outdated: true }),
      phone_stop: () => {
        throw new Error('stuck')
      },
    })
    await stopOutdatedPhoneAtStart(s.deps)
    expect(s.log).toHaveBeenCalledWith(expect.stringContaining('stuck'))
  })
  it('acts on a first answer that is slow, as a cold start with a migration is', async () => {
    vi.useFakeTimers()
    const s = setup({ phone_status: () => new Promise((r) => setTimeout(() => r({ running: true, outdated: true }), 40_000)), phone_stop: () => ({ stopped: true }) })
    const p = stopOutdatedPhoneAtStart({ ...s.deps, timeoutMs: undefined })
    await vi.advanceTimersByTimeAsync(40_000)
    await p
    expect(s.call).toHaveBeenCalledWith('phone_stop', {})
  })
})
