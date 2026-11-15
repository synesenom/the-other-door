import { describe, expect, it } from 'vitest'
import { ensureElectron, installElectron } from './electron-binary'
import { makeGlobalSetup } from './global-setup'

const io = (files: Set<string>, onInstall: () => void = () => {}) => ({
  binary: () => (files.has('path.txt') ? '/e/dist/electron' : null),
  exists: (path: string) => files.has(path),
  install: (_timeoutMs: number) => onInstall(),
})

describe('ensureElectron', () => {
  it('leaves a binary already in place alone: nothing is downloaded', () => {
    let installs = 0
    const files = new Set(['path.txt', '/e/dist/electron'])
    expect(ensureElectron(io(files, () => installs++))).toBe('/e/dist/electron')
    expect(installs).toBe(0)
  })

  it('downloads a missing binary once, then gives its path', () => {
    const files = new Set<string>()
    let installs = 0
    const fetch = () => {
      installs++
      files.add('path.txt').add('/e/dist/electron')
    }
    expect(ensureElectron(io(files, fetch))).toBe('/e/dist/electron')
    expect(installs).toBe(1)
  })

  it('downloads again when path.txt names a binary that is gone', () => {
    const files = new Set(['path.txt'])
    let installs = 0
    ensureElectron(io(files, () => { installs++; files.add('/e/dist/electron') }))
    expect(installs).toBe(1)
  })

  it('fails the run before any test when the binary is still missing after the download', () => {
    expect(() => ensureElectron(io(new Set()))).toThrow("Electron's binary is missing after its download")
  })
})

describe('installElectron', () => {
  it('fails with a clear message when the download does not finish in time, instead of hanging the run', () => {
    let timeout = 0
    const run = (_script: string, timeoutMs: number) => {
      timeout = timeoutMs
      return { status: null, error: Object.assign(new Error('spawnSync node ETIMEDOUT'), { code: 'ETIMEDOUT' }) }
    }
    expect(() => installElectron(300_000, run)).toThrow("Electron's binary did not download in 5 minutes")
    expect(timeout).toBe(300_000)
  })

  it('fails when the download exits with an error', () => {
    expect(() => installElectron(300_000, () => ({ status: 1 }))).toThrow("Electron's binary download failed (exit 1)")
  })

  it('returns when the download succeeded', () => {
    expect(() => installElectron(300_000, () => ({ status: 0 }))).not.toThrow()
  })
})

describe('the journeys global setup', () => {
  it('fetches Electron before the run starts, so no worker races to download it (#126)', () => {
    const calls: string[] = []
    makeGlobalSetup(() => { calls.push('fetch'); return '' }, () => calls.push('start'))()
    expect(calls).toEqual(['fetch', 'start'])
  })

  it('starts no run when the fetch fails', () => {
    const calls: string[] = []
    const setup = makeGlobalSetup(() => { throw new Error('no binary') }, () => calls.push('start'))
    expect(setup).toThrow('no binary')
    expect(calls).toEqual([])
  })
})
