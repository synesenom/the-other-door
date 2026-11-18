import { mkdirSync, mkdtempSync, realpathSync, symlinkSync, writeFileSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { checkPicked, doorHome, isJobId, isMaterialName, isPngName, materialPath } from './files'

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
    for (const bad of ['cv_page_x.png', 'cv.html', 'cv_page_1.pdf', '../cv_page_1.png', 'x_page_1.png']) {
      expect(isPngName(bad)).toBe(false)
    }
  })
})

describe('materialPath', () => {
  function home() {
    const h = realpathSync(mkdtempSync(join(tmpdir(), 'files-')))
    const dir = join(h, 'jobs', 'output', 'jobindex.123')
    mkdirSync(dir, { recursive: true })
    for (const f of ['cv.pdf', 'cover_letter.pdf', 'cv_page_2.png', 'cv.html']) writeFileSync(join(dir, f), 'x')
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
    expect(materialPath(h, 'jobindex.123', 'cv.html')).toBeNull()
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

describe('checkPicked', () => {
  const rule = { extensions: ['pdf', 'tar.gz'], size: { maxBytes: 10, tooBig: 'big' }, wrongType: 'wrong', unreadable: 'unread' }
  const io = (real: string, size = 1) => ({ realpath: async () => real, stat: async () => ({ size }) })
  it('accepts a right name, link target and size, returning the real path', async () => {
    expect(await checkPicked('/a/B.PDF', rule, io('/z/c.pdf', 10))).toEqual({ ok: true, real: '/z/c.pdf', size: 10 })
    expect((await checkPicked('/a/x.tar.gz', rule, io('/z/y.tar.gz'))).ok).toBe(true)
  })
  it('refuses rather than skip the size cap when the size cannot be read', async () => {
    expect(await checkPicked('/a/c.pdf', rule, { realpath: async () => '/a/c.pdf' })).toEqual({ ok: false, error: 'unread' })
  })
  it('refuses a wrong name without reading the file', async () => {
    expect(await checkPicked('/a/b.txt', rule, { stat: async () => { throw new Error('no') } })).toEqual({ ok: false, error: 'wrong' })
  })
  it('refuses a link to another type', async () => {
    expect(await checkPicked('/a/b.pdf', rule, io('/z/c.txt'))).toEqual({ ok: false, error: 'wrong' })
  })
  it('refuses a file over the cap', async () => {
    expect(await checkPicked('/a/b.pdf', rule, io('/z/c.pdf', 11))).toEqual({ ok: false, error: 'big' })
  })
  it('says unreadable when the file cannot be read', async () => {
    const bad = { realpath: async () => { throw new Error('gone') }, stat: async () => ({ size: 1 }) }
    expect(await checkPicked('/a/b.pdf', rule, bad)).toEqual({ ok: false, error: 'unread' })
  })
  it('uses the path itself and no size check without realpath or a cap', async () => {
    const r = await checkPicked('/a/b.pdf', { extensions: ['pdf'], wrongType: 'w' }, { stat: async () => { throw new Error('no') } })
    expect(r).toEqual({ ok: true, real: '/a/b.pdf', size: 0 })
  })
})
