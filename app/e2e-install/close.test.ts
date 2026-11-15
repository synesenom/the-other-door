import { describe, expect, it } from 'vitest'
import { closeApp, createTracker, killTreeCommand, sweepCommand } from './close'

const fake = (close: () => Promise<void>, pid: number | undefined = 42) => ({ close, process: () => ({ pid }) })

describe('closeApp', () => {
  it('closes the app and kills nothing when it quits in time', async () => {
    const killed: number[] = []
    await closeApp(fake(async () => {}), { timeoutMs: 1000, kill: (pid) => killed.push(pid) })
    expect(killed).toEqual([])
  })

  it('kills the app’s process tree when close hangs past the timeout', async () => {
    const killed: number[] = []
    await closeApp(fake(() => new Promise<void>(() => {})), { timeoutMs: 10, kill: (pid) => killed.push(pid) })
    expect(killed).toEqual([42])
  })

  it('kills the app’s process tree when close throws, and does not throw itself', async () => {
    const killed: number[] = []
    await closeApp(fake(async () => { throw new Error('target closed') }), { timeoutMs: 1000, kill: (pid) => killed.push(pid) })
    expect(killed).toEqual([42])
  })

  it('leaves an app that already quit alone: the test closed it on its own path', async () => {
    const killed: number[] = []
    let asked = false
    const quit = { close: async () => { asked = true }, process: () => ({ pid: 42, exitCode: 0, signalCode: null }) }
    await closeApp(quit, { timeoutMs: 10, kill: (pid) => killed.push(pid) })
    expect([asked, killed]).toEqual([false, []])
  })

  it('does not throw when the kill fails or there is no pid', async () => {
    await closeApp(fake(async () => { throw new Error('x') }), { timeoutMs: 10, kill: () => { throw new Error('gone') } })
    await closeApp(fake(async () => { throw new Error('x') }, undefined), { timeoutMs: 10, kill: () => { throw new Error('never') } })
  })
})

describe('killTreeCommand', () => {
  it('takes the children too on Windows: the bundled Python holds the install folder', () => {
    expect(killTreeCommand('win32', 42)).toEqual(['taskkill', '/PID', '42', '/T', '/F'])
  })

  it('kills the process elsewhere', () => {
    expect(killTreeCommand('darwin', 42)).toBeNull()
    expect(killTreeCommand('linux', 42)).toBeNull()
  })
})

describe('createTracker', () => {
  it('closes an app whose launch failed after it started: it was tracked as it started', async () => {
    const tracker = createTracker()
    let closed = false
    const app = { close: async () => { closed = true }, process: () => ({ pid: 7, exitCode: null, signalCode: null }) }
    // a launch that hands the app over as it starts, then fails (redirect, first window, the server not answering)
    const launch = async (onStart: (a: typeof app) => void) => { onStart(app); throw new Error('the redirected server answers') }
    await expect(launch(tracker.track)).rejects.toThrow('the redirected server answers')
    await tracker.closeAll({ timeoutMs: 10, kill: () => {} })
    expect(closed).toBe(true)
  })

  it('closes each app once, and forgets them after', async () => {
    const tracker = createTracker()
    let closes = 0
    const app = { close: async () => { closes++ }, process: () => ({ pid: 7, exitCode: null, signalCode: null }) }
    tracker.track(app)
    tracker.track(app)
    await tracker.closeAll({ timeoutMs: 10, kill: () => {} })
    await tracker.closeAll({ timeoutMs: 10, kill: () => {} })
    expect(closes).toBe(1)
  })
})

describe('sweepCommand', () => {
  it('on Windows, stops every process whose executable is under the install folder (the app, its Python, Tectonic)', () => {
    const argv = sweepCommand('win32', "C:\\Temp\\door-install-x\\app")!
    expect(argv.slice(0, 3)).toEqual(['powershell', '-NoProfile', '-Command'])
    expect(argv[3]).toContain("StartsWith('C:\\Temp\\door-install-x\\app\\', 'OrdinalIgnoreCase')")
    expect(argv[3]).toContain('Stop-Process')
  })

  it('quotes a folder with an apostrophe for PowerShell', () => {
    expect(sweepCommand('win32', "C:\\O'Neil")![3]).toContain("StartsWith('C:\\O''Neil\\'")
  })

  it('elsewhere, kills what runs from the folder by its command line', () => {
    expect(sweepCommand('darwin', '/tmp/door-install-x')).toEqual(['pkill', '-KILL', '-f', '^/tmp/door-install-x/'])
    expect(sweepCommand('linux', '/tmp/a.b')).toEqual(['pkill', '-KILL', '-f', '^/tmp/a\\.b/'])
  })
})
