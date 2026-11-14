import { describe, expect, it } from 'vitest'
import { load } from 'js-yaml'
import { mergeMacManifests } from './merge-mac-manifest'

const arm = `version: 0.2.0
files:
  - url: the-other-door-0.2.0-mac-arm64.zip
    sha512: ARMZIP
    size: 100
  - url: the-other-door-0.2.0-mac-arm64.dmg
    sha512: ARMDMG
    size: 110
path: the-other-door-0.2.0-mac-arm64.zip
sha512: ARMZIP
releaseDate: '2026-11-14T10:00:00.000Z'
`
const x64 = `version: 0.2.0
files:
  - url: the-other-door-0.2.0-mac-x64.zip
    sha512: X64ZIP
    size: 120
  - url: the-other-door-0.2.0-mac-x64.dmg
    sha512: X64DMG
    size: 130
path: the-other-door-0.2.0-mac-x64.zip
sha512: X64ZIP
releaseDate: '2026-11-14T10:05:00.000Z'
`

describe('mergeMacManifests', () => {
  const merged = load(mergeMacManifests(arm, x64)) as { version: string; files: { url: string }[]; path: string; sha512: string }
  it('keeps every file of both, once', () => {
    expect(merged.files.map((f) => f.url).sort()).toEqual([
      'the-other-door-0.2.0-mac-arm64.dmg',
      'the-other-door-0.2.0-mac-arm64.zip',
      'the-other-door-0.2.0-mac-x64.dmg',
      'the-other-door-0.2.0-mac-x64.zip',
    ])
    expect(load(mergeMacManifests(arm, arm)) as { files: unknown[] }).toMatchObject({ files: expect.any(Array) })
    expect((load(mergeMacManifests(arm, arm)) as { files: unknown[] }).files).toHaveLength(2)
  })
  it('keeps the arm64 build as the top-level file', () => {
    expect(merged.path).toBe('the-other-door-0.2.0-mac-arm64.zip')
    expect(merged.sha512).toBe('ARMZIP')
    expect(merged.version).toBe('0.2.0')
  })
  it('refuses two versions', () => {
    expect(() => mergeMacManifests(arm, x64.replace('version: 0.2.0', 'version: 0.3.0'))).toThrow(/version/)
  })
  it('refuses a manifest with no files', () => {
    expect(() => mergeMacManifests(arm, 'version: 0.2.0\n')).toThrow(/files/)
  })
})
