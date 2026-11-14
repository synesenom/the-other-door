// Updates (#501, #17): an installed app that can replace itself (signed macOS, Windows, AppImage) downloads a
// newer published release in the background and installs it on restart (electron-updater); one that cannot
// (unsigned macOS, .deb) reads the latest release from GitHub and links to its page; a checkout and the demo say
// nothing. Failures are logged and said nowhere.
export type UpdateMode = 'install' | 'link' | 'none'
export type UpdateState = 'idle' | 'downloading' | 'downloaded'
export type UpdateResult =
  | { enabled: false; current: string }
  | { enabled: true; mode: 'install' | 'link'; checked: false; current: string }
  | { enabled: true; mode: 'install' | 'link'; checked: true; current: string; available: false }
  | { enabled: true; mode: 'install' | 'link'; checked: true; current: string; available: true; version: string; url: string; state: UpdateState }

/** The one place releases are published. */
export const RELEASES_LATEST = 'https://api.github.com/repos/synesenom/the-other-door/releases/latest'
const RELEASE_PAGE = 'https://github.com/synesenom/the-other-door/releases/tag/v'

/** How this build learns of updates, from where it runs and whether it is signed (macOS cannot self-install unsigned). */
export function updateMode(o: { platform: string; packaged: boolean; simulated: boolean; doorSigned: boolean; appImage: boolean }): UpdateMode {
  if (!o.packaged || o.simulated) return 'none'
  if (o.platform === 'darwin') return o.doorSigned ? 'install' : 'link'
  if (o.platform === 'win32') return 'install'
  return o.appImage ? 'install' : 'link'
}

/** `DOOR_UPDATES=off` keeps a packaged app offline (the package and install tests only). */
export function updatesAllowed(env: Record<string, string | undefined>): boolean {
  return env['DOOR_UPDATES'] !== 'off'
}

/** The build's package.json says whether it was signed and notarized (electron-builder's extraMetadata). */
export function doorSignedOf(pkg: unknown): boolean {
  return Boolean(pkg && typeof pkg === 'object' && (pkg as Record<string, unknown>)['doorSigned'] === true)
}

const PLAIN = /^v?(\d+)\.(\d+)\.(\d+)$/

/** Negative, zero or positive like a comparator; null when either is not a plain x.y.z (a prerelease, garbage). */
export function compareVersions(a: string, b: string): number | null {
  const x = PLAIN.exec(a.trim())
  const y = PLAIN.exec(b.trim())
  if (!x || !y) return null
  for (let i = 1; i <= 3; i++) {
    const d = Number(x[i]) - Number(y[i])
    if (d !== 0) return d
  }
  return 0
}

/** GitHub's `releases/latest` shape: the version and the page to download from. */
export function parseLatest(payload: unknown): { version: string; url: string } | null {
  if (!payload || typeof payload !== 'object') return null
  const p = payload as Record<string, unknown>
  if (p['prerelease'] === true || p['draft'] === true) return null
  const tag = p['tag_name']
  const url = p['html_url']
  if (typeof tag !== 'string' || typeof url !== 'string') return null
  const m = PLAIN.exec(tag.trim())
  if (!m || !url.startsWith('https://')) return null
  return { version: `${m[1]}.${m[2]}.${m[3]}`, url }
}

interface FetchLike {
  (url: string, init: { headers: Record<string, string>; signal: AbortSignal }): Promise<{ ok: boolean; status: number; json(): Promise<unknown> }>
}

type CheckResult =
  | { enabled: false; current: string }
  | { enabled: true; checked: false; current: string }
  | { enabled: true; checked: true; current: string; available: false }
  | { enabled: true; checked: true; current: string; available: true; version: string; url: string }

export function createUpdateChecker(opts: { feed: string; current: string; fetch: FetchLike; log: (message: string) => void; timeoutMs?: number }) {
  const { feed, current } = opts
  const enabled = feed.startsWith('https://')
  let cached: CheckResult | null = null
  async function check(): Promise<CheckResult> {
    if (!enabled) return { enabled: false, current }
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), opts.timeoutMs ?? 8000)
    try {
      const res = await opts.fetch(feed, { headers: { Accept: 'application/json', 'User-Agent': `door/${current}` }, signal: controller.signal })
      if (!res.ok) throw new Error(`the feed answered ${res.status}`)
      const latest = parseLatest(await res.json())
      if (!latest) throw new Error('the feed has no usable release')
      const order = compareVersions(latest.version, current)
      cached =
        order !== null && order > 0
          ? { enabled: true, checked: true, current, available: true, version: latest.version, url: latest.url }
          : { enabled: true, checked: true, current, available: false }
    } catch (e) {
      opts.log(`update check failed: ${e instanceof Error ? e.message : String(e)}`)
      cached = { enabled: true, checked: false, current }
    } finally {
      clearTimeout(timer)
    }
    return cached
  }
  return { check, last: () => cached }
}

/** The part of electron-updater's `autoUpdater` used here, so a test can stand in for it. */
export interface UpdaterLike {
  autoDownload: boolean
  autoInstallOnAppQuit: boolean
  checkForUpdates(): Promise<unknown>
  quitAndInstall(): void
  on(event: string, listener: (...args: any[]) => void): unknown
}

export function createUpdateManager(opts: {
  mode: UpdateMode
  current: string
  updater: UpdaterLike | null
  fetch: FetchLike
  log: (message: string) => void
  onState?: (result: UpdateResult) => void
  timeoutMs?: number
}) {
  const { mode, current } = opts
  let cached: UpdateResult | null = null
  const listeners = new Set<(result: UpdateResult) => void>()
  const set = (r: UpdateResult) => {
    cached = r
    opts.onState?.(r)
    listeners.forEach((l) => l(r))
  }
  const unchecked = (): UpdateResult => ({ enabled: true, mode: 'install', checked: false, current })
  const updater = mode === 'install' ? opts.updater : null
  let errored = false // electron-updater emits `error` and also rejects: one log line
  if (updater) {
    updater.autoDownload = true
    updater.autoInstallOnAppQuit = true
    const found = (state: UpdateState) => (info: { version?: string }) => {
      const version = String(info?.version ?? '')
      set({ enabled: true, mode: 'install', checked: true, current, available: true, version, url: RELEASE_PAGE + version, state })
    }
    updater.on('update-available', found('downloading'))
    updater.on('update-downloaded', found('downloaded'))
    updater.on('update-not-available', () => set({ enabled: true, mode: 'install', checked: true, current, available: false }))
    updater.on('error', (e: unknown) => {
      opts.log(`update check failed: ${e instanceof Error ? e.message : String(e)}`)
      errored = true
      // a failed download is announced here too: go back to a state that can be checked again
      if (!(cached && cached.enabled && cached.checked && cached.available && cached.state === 'downloaded')) set(unchecked())
    })
  }
  const checker = mode === 'link' ? createUpdateChecker({ feed: RELEASES_LATEST, current, fetch: opts.fetch, log: opts.log, timeoutMs: opts.timeoutMs }) : null

  async function check(): Promise<UpdateResult> {
    if (mode === 'none') return { enabled: false, current }
    if (checker) {
      const r = await checker.check()
      const out: UpdateResult = !r.enabled ? r : r.checked && r.available ? { ...r, mode: 'link', state: 'idle' } : { ...r, mode: 'link' }
      set(out)
      return out
    }
    if (cached && cached.enabled && cached.checked && cached.available) return cached // downloading or downloaded: leave it be
    errored = false
    try {
      await updater?.checkForUpdates()
    } catch (e) {
      if (!errored) opts.log(`update check failed: ${e instanceof Error ? e.message : String(e)}`)
      set(unchecked())
    }
    return cached ?? unchecked()
  }

  function install(): { ok: boolean } {
    if (mode !== 'install' || !updater || !cached || !cached.enabled || !cached.checked || !cached.available || cached.state !== 'downloaded') return { ok: false }
    updater.quitAndInstall()
    return { ok: true }
  }

  /** Tell `listener` each change of state; returns the way to stop. */
  function subscribe(listener: (result: UpdateResult) => void): () => void {
    listeners.add(listener)
    return () => listeners.delete(listener)
  }

  return { check, last: () => cached, install, subscribe }
}
