import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { electronBinary } from './electron-binary'

describe('electronBinary', () => {
  it('fetches the binary through the loader once, before any worker launches it (#126)', () => {
    const dir = mkdtempSync(join(tmpdir(), 'electron-binary-'))
    const binary = join(dir, 'electron')
    let loads = 0
    const load = () => {
      loads++
      writeFileSync(binary, '')
      return binary
    }
    expect(electronBinary(load)).toBe(binary)
    expect(loads).toBe(1)
  })

  it('fails the run before any test when the binary is still missing after the fetch', () => {
    expect(() => electronBinary(() => '/nowhere/electron')).toThrow('/nowhere/electron')
  })

  it('finds the real Electron binary in place', () => {
    expect(electronBinary()).toMatch(/electron/i)
  })
})
