// Update check (#501): read the latest release from a feed, say when it is newer than this app. It installs
// nothing and sends nothing but a plain GET; offline or unreachable it is silent and logs one line.
export type UpdateResult =
  | { enabled: false; current: string }
  | { enabled: true; checked: false; current: string }
  | { enabled: true; checked: true; current: string; available: false }
  | { enabled: true; checked: true; current: string; available: true; version: string; url: string }

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

export function createUpdateChecker(opts: { feed: string; current: string; fetch: FetchLike; log: (message: string) => void; timeoutMs?: number }) {
  const { feed, current } = opts
  const enabled = feed.startsWith('https://')
  let cached: UpdateResult | null = null
  async function check(): Promise<UpdateResult> {
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
