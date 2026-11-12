import { describe, expect, it, vi } from 'vitest'
import { compareVersions, createUpdateChecker, parseLatest } from './updates'

describe('compareVersions', () => {
  it('orders numerically, ignoring a v prefix', () => {
    expect(compareVersions('0.1.0', '0.1.1')).toBeLessThan(0)
    expect(compareVersions('0.1.10', '0.1.9')).toBeGreaterThan(0)
    expect(compareVersions('v0.2.0', '0.2.0')).toBe(0)
  })
  it('knows no order for a prerelease or garbage', () => {
    expect(compareVersions('0.2.0-rc1', '0.1.0')).toBeNull()
    expect(compareVersions('abc', '0.1.0')).toBeNull()
  })
})

describe('parseLatest', () => {
  const ok = { tag_name: 'v0.1.1', html_url: 'https://github.com/o/r/releases/tag/v0.1.1', prerelease: false, draft: false }
  it('reads a release', () => {
    expect(parseLatest(ok)).toEqual({ version: '0.1.1', url: ok.html_url })
  })
  it.each([
    ['prerelease', { ...ok, prerelease: true }],
    ['draft', { ...ok, draft: true }],
    ['no tag', { ...ok, tag_name: undefined }],
    ['no url', { ...ok, html_url: undefined }],
    ['http url', { ...ok, html_url: 'http://example.com/x' }],
    ['bad tag', { ...ok, tag_name: 'nightly' }],
    ['a string', 'x'],
    ['null', null],
  ])('refuses %s', (_n, payload) => {
    expect(parseLatest(payload)).toBeNull()
  })
})

const FEED = 'https://api.github.com/repos/o/r/releases/latest'
const release = { tag_name: 'v0.1.1', html_url: 'https://github.com/o/r/releases/tag/v0.1.1' }
const reply = (body: unknown, status = 200) => async () => ({ ok: status === 200, status, json: async () => body })

function make(fetch: (url: string, init: { headers: Record<string, string>; signal: AbortSignal }) => Promise<any>, feed = FEED, timeoutMs = 50) {
  const log = vi.fn()
  return { log, checker: createUpdateChecker({ feed, current: '0.1.0', fetch, log, timeoutMs }) }
}

describe('createUpdateChecker', () => {
  it('does nothing without a feed', async () => {
    const fetch = vi.fn()
    const { checker, log } = make(fetch, '')
    expect(await checker.check()).toEqual({ enabled: false, current: '0.1.0' })
    expect(fetch).not.toHaveBeenCalled()
    expect(log).not.toHaveBeenCalled()
  })

  it('does nothing for a feed that is not https', async () => {
    const fetch = vi.fn()
    const { checker } = make(fetch, 'http://example.com/x')
    expect((await checker.check()).enabled).toBe(false)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('says a newer version is available', async () => {
    const { checker } = make(reply(release))
    expect(await checker.check()).toEqual({ enabled: true, checked: true, current: '0.1.0', available: true, version: '0.1.1', url: release.html_url })
  })

  it('says nothing is available for the same or an older version', async () => {
    for (const tag of ['v0.1.0', 'v0.0.9']) {
      const { checker } = make(reply({ ...release, tag_name: tag }))
      expect(await checker.check()).toMatchObject({ enabled: true, checked: true, available: false })
    }
  })

  it.each([
    ['rejected fetch', async () => { throw new Error('offline') }],
    ['non-200', reply({}, 404)],
    ['invalid json', async () => ({ ok: true, status: 200, json: async () => { throw new Error('bad') } })],
    ['unparseable payload', reply({ nothing: 1 })],
    ['hang', (_u: string, init: { signal: AbortSignal }) => new Promise((_res, rej) => init.signal.addEventListener('abort', () => rej(new Error('aborted'))))],
  ])('a failure (%s) is unchecked and logged once', async (_n, fetch) => {
    const { checker, log } = make(fetch as any)
    expect(await checker.check()).toEqual({ enabled: true, checked: false, current: '0.1.0' })
    expect(log).toHaveBeenCalledTimes(1)
  })

  it('sends only Accept and a door user-agent', async () => {
    const fetch = vi.fn(reply(release))
    const { checker } = make(fetch as any)
    await checker.check()
    const [url, init] = fetch.mock.calls[0] as unknown as [string, { headers: Record<string, string> }]
    expect(url).toBe(FEED)
    expect(Object.keys(init.headers).sort()).toEqual(['Accept', 'User-Agent'])
    expect(init.headers['User-Agent']).toMatch(/door/i)
  })

  it('keeps the last result', async () => {
    const { checker } = make(reply(release))
    expect(checker.last()).toBeNull()
    const r = await checker.check()
    expect(checker.last()).toEqual(r)
  })
})
