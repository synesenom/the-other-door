import { mkdirSync, mkdtempSync, realpathSync, symlinkSync, writeFileSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { doorHome, isJobId, isMaterialName, isPngName, materialPath } from './files'

describe('doorHome', () => {
  it('prefers a non-empty DOOR_HOME, resolved', () => {
    expect(doorHome({ DOOR_HOME: '/data/h/../store' }, '/repo')).toBe(resolve('/data/store'))
  })
  it('expands a leading ~', () => {
    expect(doorHome({ DOOR_HOME: '~/door-data' }, '/repo')).toBe(join(homedir(), 'door-data'))
    expect(doorHome({ DOOR_HOME: '~' }, '/repo')).toBe(homedir())
  })
  it('falls back to the repo when empty or unset', () => {
    expect(doorHome({}, '/repo')).toBe(resolve('/repo'))
    expect(doorHome({ DOOR_HOME: '' }, '/repo')).toBe(resolve('/repo'))
  })
})

describe('names', () => {
  it('isJobId', () => {
    expect(isJobId('jobindex.123')).toBe(true)
    for (const bad of ['', '..', '.', 'a/b', 'a\\b', 'a/../b', 7, undefined]) expect(isJobId(bad)).toBe(false)
  })
  it('isMaterialName', () => {
    expect(isMaterialName('cv')).toBe(true)
    expect(isMaterialName('cover_letter')).toBe(true)
    for (const bad of ['cv.pdf', 'other', '', 3]) expect(isMaterialName(bad)).toBe(false)
  })
  it('isPngName', () => {
    expect(isPngName('cv_page_2.png')).toBe(true)
    expect(isPngName('cover_letter_page_1.png')).toBe(true)
    for (const bad of ['cv_page_x.png', 'cv.tex', 'cv_page_1.pdf', '../cv_page_1.png', 'x_page_1.png']) {
      expect(isPngName(bad)).toBe(false)
    }
  })
})

describe('materialPath', () => {
  function home() {
    const h = realpathSync(mkdtempSync(join(tmpdir(), 'files-')))
    const dir = join(h, 'jobs', 'output', 'jobindex.123')
    mkdirSync(dir, { recursive: true })
    for (const f of ['cv.pdf', 'cover_letter.pdf', 'cv_page_2.png', 'cv.tex']) writeFileSync(join(dir, f), 'x')
    return { h, dir }
  }
  it('accepts the known files', () => {
    const { h, dir } = home()
    expect(materialPath(h, 'jobindex.123', 'cv.pdf')).toBe(join(dir, 'cv.pdf'))
    expect(materialPath(h, 'jobindex.123', 'cv_page_2.png')).toBe(join(dir, 'cv_page_2.png'))
  })
  it('reads the copy kept when the application was sent, from its sent folder', () => {
    const { h, dir } = home()
    mkdirSync(join(dir, 'sent'))
    writeFileSync(join(dir, 'sent', 'cv.pdf'), 'sent')
    expect(materialPath(h, 'jobindex.123', 'cv.pdf', true)).toBe(join(dir, 'sent', 'cv.pdf'))
    expect(materialPath(h, 'jobindex.123', 'cover_letter.pdf', true)).toBeNull() // not in the sent copy
  })
  it('refuses odd ids and names', () => {
    const { h } = home()
    expect(materialPath(h, '..', 'cv.pdf')).toBeNull()
    expect(materialPath(h, 'a/../b', 'cv.pdf')).toBeNull()
    expect(materialPath(h, '', 'cv.pdf')).toBeNull()
    expect(materialPath(h, 'jobindex.123', '../cv.pdf')).toBeNull()
    expect(materialPath(h, 'jobindex.123', 'cv.tex')).toBeNull()
    expect(materialPath(h, 'jobindex.123', 'cv_page_x.png')).toBeNull()
  })
  it('returns null for a missing file', () => {
    const { h } = home()
    expect(materialPath(h, 'jobindex.123', 'cover_letter_page_1.png')).toBeNull()
    expect(materialPath(h, 'nope.1', 'cv.pdf')).toBeNull()
  })
  it('refuses a symlink that leaves jobs/output', () => {
    const { h, dir } = home()
    const outside = join(h, 'secret.png')
    writeFileSync(outside, 'secret')
    symlinkSync(outside, join(dir, 'cv_page_1.png'))
    expect(materialPath(h, 'jobindex.123', 'cv_page_1.png')).toBeNull()
  })
})
