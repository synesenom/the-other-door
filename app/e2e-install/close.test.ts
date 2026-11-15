import { describe, expect, it } from 'vitest'
import { closeApp, killTreeCommand } from './close'

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
