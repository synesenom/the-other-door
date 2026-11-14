import { describe, expect, it, vi } from 'vitest'
import { compareVersions, createUpdateChecker, createUpdateManager, doorSignedOf, parseLatest, updateMode, updatesAllowed, RELEASES_LATEST } from './updates'

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

describe('updateMode', () => {
  const base = { platform: 'linux', packaged: true, simulated: false, doorSigned: false, appImage: false }
  it.each([
    [{ packaged: false }, 'none'],
    [{ simulated: true }, 'none'],
    [{ platform: 'darwin', doorSigned: true }, 'install'],
    [{ platform: 'darwin', doorSigned: false }, 'link'],
    [{ platform: 'win32' }, 'install'],
    [{ platform: 'linux', appImage: true }, 'install'],
    [{ platform: 'linux', appImage: false }, 'link'],
  ])('%j is %s', (over, mode) => {
    expect(updateMode({ ...base, ...over })).toBe(mode)
  })
})

describe('updatesAllowed', () => {
  it('is off only for DOOR_UPDATES=off', () => {
    expect(updatesAllowed({ DOOR_UPDATES: 'off' })).toBe(false)
    expect(updatesAllowed({})).toBe(true)
  })
})

describe('doorSignedOf', () => {
  it('is true only for doorSigned: true', () => {
    expect(doorSignedOf({ doorSigned: true })).toBe(true)
    expect(doorSignedOf({ doorSigned: 'true' })).toBe(false)
    expect(doorSignedOf({})).toBe(false)
    expect(doorSignedOf(null)).toBe(false)
  })
})

type Handler = (...args: any[]) => void
function fakeUpdater(onCheck: (emit: (event: string, ...a: any[]) => void) => Promise<unknown> | void = () => undefined) {
  const handlers: Record<string, Handler[]> = {}
  const emit = (event: string, ...a: any[]) => (handlers[event] ?? []).forEach((h) => h(...a))
  return {
    autoDownload: false,
    autoInstallOnAppQuit: false,
    checkForUpdates: vi.fn(async () => onCheck(emit)),
    quitAndInstall: vi.fn(),
    on(event: string, fn: Handler) {
      ;(handlers[event] ??= []).push(fn)
    },
    emit,
  }
}

function manager(mode: 'install' | 'link' | 'none', updater = fakeUpdater(), fetch: any = reply({ tag_name: 'v0.1.1', html_url: 'https://github.com/o/r/releases/tag/v0.1.1' })) {
  const log = vi.fn()
  const onState = vi.fn()
  const m = createUpdateManager({ mode, current: '0.1.0', updater, fetch, log, onState })
  return { m, updater, log, onState, fetch }
}

describe('createUpdateManager', () => {
  it('install: downloads in the background and installs when the app quits', () => {
    const { updater } = manager('install')
    expect(updater.autoDownload).toBe(true)
    expect(updater.autoInstallOnAppQuit).toBe(true)
  })

  it('install: an available update is downloading, then downloaded', async () => {
    const updater = fakeUpdater((emit) => emit('update-available', { version: '0.1.1' }))
    const { m, onState } = manager('install', updater)
    expect(await m.check()).toMatchObject({ enabled: true, mode: 'install', checked: true, available: true, version: '0.1.1', state: 'downloading' })
    updater.emit('update-downloaded', { version: '0.1.1' })
    expect(m.last()).toMatchObject({ available: true, version: '0.1.1', state: 'downloaded' })
    expect(onState).toHaveBeenCalledTimes(2)
  })

  it('install: nothing new is available:false', async () => {
    const updater = fakeUpdater((emit) => emit('update-not-available', { version: '0.1.0' }))
    const { m } = manager('install', updater)
    expect(await m.check()).toEqual({ enabled: true, mode: 'install', checked: true, current: '0.1.0', available: false })
  })

  it('install: an error is logged once and unchecked, never thrown', async () => {
    const updater = fakeUpdater((emit) => emit('error', new Error('boom')))
    const { m, log } = manager('install', updater)
    expect(await m.check()).toEqual({ enabled: true, mode: 'install', checked: false, current: '0.1.0' })
    expect(log).toHaveBeenCalledWith(expect.stringContaining('boom'))
  })

  it('install: a rejected check is logged and unchecked', async () => {
    const updater = fakeUpdater(async () => {
      throw new Error('offline')
    })
    const { m, log } = manager('install', updater)
    expect(await m.check()).toMatchObject({ enabled: true, checked: false })
    expect(log).toHaveBeenCalledTimes(1)
  })

  it('install: a failed download goes back to unchecked and the next check asks again', async () => {
    const updater = fakeUpdater((emit) => emit('update-available', { version: '0.1.1' }))
    const { m, log } = manager('install', updater)
    await m.check()
    expect(m.last()).toMatchObject({ state: 'downloading' })
    updater.emit('error', new Error('download broke'))
    expect(m.last()).toEqual({ enabled: true, mode: 'install', checked: false, current: '0.1.0' })
    expect(log).toHaveBeenCalledTimes(1)
    await m.check()
    expect(updater.checkForUpdates).toHaveBeenCalledTimes(2)
    expect(m.last()).toMatchObject({ available: true, state: 'downloading' })
  })

  it('install: an error after the download finished keeps it downloaded', async () => {
    const updater = fakeUpdater((emit) => emit('update-available', { version: '0.1.1' }))
    const { m } = manager('install', updater)
    await m.check()
    updater.emit('update-downloaded', { version: '0.1.1' })
    updater.emit('error', new Error('later'))
    expect(m.last()).toMatchObject({ state: 'downloaded' })
  })

  it('install: a check that both emits error and rejects is logged once', async () => {
    const updater = fakeUpdater()
    updater.checkForUpdates.mockImplementation(async () => {
      const e = new Error('offline')
      updater.emit('error', e)
      throw e
    })
    const { m, log } = manager('install', updater)
    expect(await m.check()).toMatchObject({ checked: false })
    expect(log).toHaveBeenCalledTimes(1)
  })

  it('install(): restarts only when downloaded', async () => {
    const updater = fakeUpdater((emit) => emit('update-available', { version: '0.1.1' }))
    const { m } = manager('install', updater)
    expect(m.install()).toEqual({ ok: false })
    await m.check()
    expect(m.install()).toEqual({ ok: false })
    updater.emit('update-downloaded', { version: '0.1.1' })
    expect(m.install()).toEqual({ ok: true })
    expect(updater.quitAndInstall).toHaveBeenCalledTimes(1)
  })

  it('a downloaded update is not checked again', async () => {
    const updater = fakeUpdater((emit) => emit('update-available', { version: '0.1.1' }))
    const { m } = manager('install', updater)
    await m.check()
    updater.emit('update-downloaded', { version: '0.1.1' })
    await m.check()
    expect(updater.checkForUpdates).toHaveBeenCalledTimes(1)
  })

  it('link: the release feed answers and the updater is left alone', async () => {
    const { m, updater, fetch } = manager('link')
    expect(await m.check()).toMatchObject({ enabled: true, mode: 'link', checked: true, available: true, version: '0.1.1', state: 'idle', url: 'https://github.com/o/r/releases/tag/v0.1.1' })
    expect(updater.checkForUpdates).not.toHaveBeenCalled()
    expect(updater.autoDownload).toBe(false)
    expect(m.install()).toEqual({ ok: false })
    expect(RELEASES_LATEST).toMatch(/^https:\/\/api\.github\.com\//)
    expect(fetch).toBeDefined()
  })

  it('none: says nothing', async () => {
    const fetch = vi.fn()
    const { m, updater } = manager('none', fakeUpdater(), fetch)
    expect(await m.check()).toEqual({ enabled: false, current: '0.1.0' })
    expect(fetch).not.toHaveBeenCalled()
    expect(updater.checkForUpdates).not.toHaveBeenCalled()
  })
})
