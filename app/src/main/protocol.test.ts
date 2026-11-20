import { mkdirSync, mkdtempSync, realpathSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { resolveMaterialRequest, resolvePhotoRequest } from './protocol'

function home() {
  const h = realpathSync(mkdtempSync(join(tmpdir(), 'proto-')))
  const dir = join(h, 'jobs', 'output', 'jobindex.123')
  mkdirSync(dir, { recursive: true })
  for (const f of ['cv_page_1.png', 'cv.pdf']) writeFileSync(join(dir, f), 'x')
  return { h, dir }
}

describe('resolveMaterialRequest', () => {
  it('maps a page image url to its file, ignoring the cache counter', () => {
    const { h, dir } = home()
    expect(resolveMaterialRequest('door-file://output/jobindex.123/cv_page_1.png?v=3', h)).toBe(join(dir, 'cv_page_1.png'))
  })
  it('maps a page image of the copy that was sent', () => {
    const { h, dir } = home()
    mkdirSync(join(dir, 'sent'))
    writeFileSync(join(dir, 'sent', 'cv_page_1.png'), 'x')
    expect(resolveMaterialRequest('door-file://output/jobindex.123/sent/cv_page_1.png?v=1', h)).toBe(join(dir, 'sent', 'cv_page_1.png'))
  })
  it('refuses everything else', () => {
    const { h, dir } = home()
    writeFileSync(join(h, 'secret.png'), 's')
    symlinkSync(join(h, 'secret.png'), join(dir, 'cv_page_2.png'))
    for (const bad of [
      'door-file://other/jobindex.123/cv_page_1.png',
      'door-file://output/jobindex.123/cv.pdf',
      'door-file://output/../cv_page_1.png',
      'door-file://output/%2e%2e/jobindex.123/cv_page_1.png',
      'door-file://output/jobindex.123%2fcv_page_1.png',
      'door-file://output/jobindex.123%5ccv_page_1.png',
      'door-file://output/jobindex.123%5Ccv_page_1.png',
      'door-file://output/jobindex.123/cv_page_2.png',
      'door-file://output/nope.1/cv_page_1.png',
      'door-file://output/jobindex.123/',
      'door-file://output/jobindex.123/cv_page_1.png/extra',
      'door-file://output/jobindex.123/other/cv_page_1.png',
      'door-file://output/jobindex.123/sent/cv_page_9.png',
      'door-file://output/jobindex.123/sent/sent/cv_page_1.png',
      'not a url',
    ]) {
      expect(resolveMaterialRequest(bad, h), bad).toBeNull()
    }
  })
})

describe('resolvePhotoRequest', () => {
  it('serves the profile photo, ignoring the cache counter, and nothing else', () => {
    const { h } = home()
    mkdirSync(join(h, 'profile'))
    writeFileSync(join(h, 'profile', 'photo.jpg'), 'x')
    writeFileSync(join(h, 'profile', 'cv.md'), 'x')
    expect(resolvePhotoRequest('door-file://profile/photo.jpg?v=3', h)).toBe(join(h, 'profile', 'photo.jpg'))
    for (const bad of [
      'door-file://profile/cv.md',
      'door-file://profile/photo.png',
      'door-file://profile/../jobs/output/jobindex.123/cv.pdf',
      'door-file://profile/%2e%2e/photo.jpg',
      'door-file://other/photo.jpg',
      'door-file://profile/photo.jpg/extra',
      'not a url',
    ]) {
      expect(resolvePhotoRequest(bad, h), bad).toBeNull()
    }
  })

  it('is null when there is no photo, or it is a link out of the profile folder', () => {
    const { h } = home()
    mkdirSync(join(h, 'profile'))
    expect(resolvePhotoRequest('door-file://profile/photo.jpg', h)).toBeNull()
    writeFileSync(join(h, 'secret.jpg'), 's')
    symlinkSync(join(h, 'secret.jpg'), join(h, 'profile', 'photo.jpg'))
    expect(resolvePhotoRequest('door-file://profile/photo.jpg', h)).toBeNull()
  })
})
