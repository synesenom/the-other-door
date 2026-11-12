// The phone app's window.door (#303): the desktop renderer's one way out, over `door serve` (#302)
// instead of Electron's IPC. Every tool call is a JSON-RPC `tools/call` to /mcp with this phone's
// device token; the answer comes back in the desktop app's Envelope, so the screens cannot tell the two
// apart. Over HTTP the long tools return `started` at once (a phone sleeps, a tunnel cuts long
// requests): this follows the run through `status_summary.in_progress` and `job_result`, so the
// screen still gets one answer at the end. What only the door machine can do (file dialogs, signing
// in, export and import) says so.
import type { Envelope } from '../main/ipc'
import type { LoginState } from '../main/claude-login'
import type { PickResult } from '../main/cv-sources'
import type { NoticeTarget } from '../main/notices'
import type { RunBoard } from '../main/run-board'

type Progress = { progress: number; total?: number; message: string }

export interface WebDeps {
  fetch: typeof fetch
  /** This phone's device token (IndexedDB), or null before pairing. */
  token(): Promise<string | null>
  /** The server said 401: the token was revoked or is from another instance. */
  onUnpaired(): void
  pollMs?: number
  visible(): boolean
  /** Resolves when the page is visible again (polling pauses while it is hidden). */
  whenVisible(): Promise<void>
  open(url: string): void
  /** Save a same-origin file under a name: the browser's own download. */
  download(url: string, name: string): void
}

export const LONG_TOOLS = new Set(['find_jobs', 'prepare'])
export const ON_THE_MACHINE = 'Do this on the computer running The other door.'
const UNREACHABLE = "Can't reach The other door. Is the computer on? If it restarted, set your phone up again on it and scan the new code."
/** What a tunnel answers with no computer behind it (502-504, Cloudflare's 52x and 530). */
const NOTHING_BEHIND = (status: number) => (status >= 502 && status <= 504) || (status >= 520 && status <= 530)
const UNPAIRED = 'This phone is no longer paired with The other door. Pair it again with a new code.'

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const base = (path: string) => path.split(/[\\/]/).filter(Boolean).pop() ?? ''

export function createWebDoor(deps: WebDeps) {
  const pollMs = deps.pollMs ?? 2000
  const listeners = new Map<string, (p: Progress) => void>()
  let rpcId = 0
  // Runs being followed: until each answer is in, the board keeps its last steps (no blank board in between).
  let following = 0
  // Where to go, from inside the phone app (a shared ad's posting): held until App listens.
  const openers = new Set<(t: NoticeTarget) => void>()
  let held: NoticeTarget[] = []

  /** One tools/call; the parsed result, or a failed envelope. */
  async function rpc(tool: string, args: Record<string, unknown>): Promise<Envelope> {
    const token = await deps.token()
    let response: Response
    try {
      response = await deps.fetch('/mcp', {
        method: 'POST',
        headers: {
          Accept: 'application/json, text/event-stream',
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ jsonrpc: '2.0', id: ++rpcId, method: 'tools/call', params: { name: tool, arguments: args } }),
      })
    } catch {
      return { ok: false, error: UNREACHABLE }
    }
    if (response.status === 401) {
      deps.onUnpaired()
      return { ok: false, error: UNPAIRED }
    }
    if (response.status === 429) return { ok: false, error: 'Too many wrong attempts from here; try again in a while.' }
    if (NOTHING_BEHIND(response.status)) return { ok: false, error: UNREACHABLE }
    if (!response.ok) return { ok: false, error: `The other door answered ${response.status}.` }
    let text = ''
    try {
      const body = await response.json()
      if (body.error) return { ok: false, error: String(body.error.message ?? 'The other door refused the call.') }
      const block = body.result?.content?.[0]
      text = block?.type === 'text' ? String(block.text) : ''
      if (body.result?.isError) return { ok: false, error: text || `${tool} failed` }
    } catch {
      return { ok: false, error: UNREACHABLE }
    }
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch {
      return { ok: false, error: `${tool} returned something that is not JSON` }
    }
    if (isObject(parsed) && typeof parsed.error === 'string') {
      return {
        ok: false,
        error: parsed.error,
        ...(Array.isArray(parsed.candidates) ? { candidates: parsed.candidates as never } : {}),
        ...(parsed.conflict === true ? { conflict: true as const } : {}),
      }
    }
    return { ok: true, data: parsed }
  }

  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
  const tick = async () => {
    await sleep(pollMs)
    if (!deps.visible()) await deps.whenVisible()
  }

  /** A started run, followed until it ends: progress lines to `callId`'s listener, then its answer. */
  async function follow(tool: string, callId: string | undefined): Promise<Envelope> {
    following += 1
    try {
      return await followUntilDone(tool, callId)
    } finally {
      following -= 1
    }
  }

  async function followUntilDone(tool: string, callId: string | undefined): Promise<Envelope> {
    let n = 0
    for (;;) {
      await tick()
      const listener = callId ? listeners.get(callId) : undefined
      if (listener) {
        const s = await rpc('status_summary', {})
        const live = s.ok && isObject(s.data) && isObject(s.data.in_progress) ? s.data.in_progress : null
        if (live && typeof live.message === 'string') listener({ progress: ++n, message: live.message })
      }
      const r = await rpc('job_result', { tool })
      if (!r.ok) {
        // a dropped connection or a tunnel's hiccup: ask again on the next tick; else it is the run's own error
        if (r.error === UNREACHABLE || r.error.startsWith('The other door answered')) continue
        return { ok: false, error: r.error }
      }
      const d = r.data as Record<string, unknown>
      if (d.running) continue
      if (d.cancelled) return { ok: false, error: 'Stopped.', stopped: true }
      if (typeof d.error === 'string') return { ok: false, error: d.error }
      return { ok: true, data: d.result }
    }
  }

  async function board(): Promise<RunBoard> {
    const s = await rpc('status_summary', {})
    const live = s.ok && isObject(s.data) ? s.data.in_progress : null
    if (!isObject(live)) return { active: false }
    const [find, prep] = await Promise.all([rpc('job_result', { tool: 'find_jobs' }), rpc('job_result', { tool: 'prepare' })])
    const running = (e: Envelope) => e.ok && isObject(e.data) && e.data.running === true
    return {
      active: true,
      own: running(find) || running(prep), // started through this server: Stop can end it
      started_at: typeof live.started_at === 'string' ? live.started_at : '',
      purpose: typeof live.purpose === 'string' ? live.purpose : '',
      message: typeof live.message === 'string' ? live.message : '',
      steps: Array.isArray(live.steps) ? (live.steps as RunBoard extends { steps: infer S } ? S : never) : [],
    }
  }

  const machineOnly = async (..._args: unknown[]) => ({ ok: false as const, error: ON_THE_MACHINE })
  const loginState: LoginState = { state: 'failed', message: 'Sign in to Claude on the computer running The other door.' }

  return {
    async call(tool: string, args: Record<string, unknown> = {}, callId?: string): Promise<Envelope> {
      const r = await rpc(tool, args)
      if (r.ok && LONG_TOOLS.has(tool) && isObject(r.data) && r.data.started === true) return follow(tool, callId)
      return r
    },
    onProgress(callId: string, cb: (p: Progress) => void): () => void {
      listeners.set(callId, cb)
      return () => listeners.delete(callId)
    },
    async openExternal(url: string) {
      if (!/^https?:\/\//i.test(url)) return { ok: false, error: 'Only web links open from The other door.' }
      deps.open(url)
      return { ok: true }
    },
    async saveMaterial(jobId: string, which: 'cv' | 'cover_letter', sent: boolean, name: string) {
      deps.download(`/files/jobs/output/${encodeURIComponent(jobId)}/${sent ? 'sent/' : ''}${which}.pdf`, name)
      return { ok: true }
    },
    /** The address of a prepared page image (the /files cookie set at pairing lets an <img> load it). */
    pageUrl(jobId: string, pngPath: string, v: number, sent = false): string {
      return `/files/jobs/output/${encodeURIComponent(jobId)}/${sent ? 'sent/' : ''}${encodeURIComponent(base(pngPath))}?v=${v}`
    },
    async pickCvFiles(): Promise<PickResult> {
      return { files: [], refused: [] }
    },
    async dropCvFiles(): Promise<PickResult> {
      return { files: [], refused: [] }
    },
    draftCv: machineOnly,
    async clearCvSources() {},
    async pickPhoto() {
      return { error: ON_THE_MACHINE }
    },
    savePhoto: machineOnly,
    claudeLogin: {
      start: machineOnly,
      sendCode: machineOnly,
      openPage: machineOnly,
      async cancel() {
        return { ok: true }
      },
      async state() {
        return loginState
      },
      onState: () => () => undefined,
    },
    async info() {
      return { demo: false, remote: true as const }
    },
    exportData: machineOnly,
    async pickArchive() {
      return { error: ON_THE_MACHINE }
    },
    importData: machineOnly,
    reportProblem: machineOnly,
    async showHome() {
      return { ok: false }
    },
    async checkUpdate() {
      return { enabled: false as const }
    },
    async stopRun() {
      const r = await rpc('cancel_job', {})
      return r.ok ? { ok: true } : { ok: false, error: r.error }
    },
    showRun: machineOnly,
    runBoard: board,
    onRunBoard(cb: (b: RunBoard) => void): () => void {
      let live = true
      let last = ''
      void (async () => {
        while (live) {
          const b = await board().catch(() => ({ active: false }) as RunBoard)
          // the run is over but its answer is not collected yet: keep showing its steps
          if (!b.active && following > 0 && last) {
            await tick()
            continue
          }
          const key = JSON.stringify(b)
          if (live && key !== last) {
            last = key
            cb(b)
          }
          await tick()
        }
      })()
      return () => {
        live = false
      }
    },
    /** Tells App where to go (App listens through onOpen, as it does for the desktop's notifications). */
    openTarget(target: NoticeTarget): void {
      if (openers.size === 0) held.push(target)
      else for (const cb of openers) cb(target)
    },
    onOpen(cb: (target: NoticeTarget) => void): () => void {
      openers.add(cb)
      const waiting = held
      held = []
      for (const t of waiting) cb(t)
      return () => openers.delete(cb)
    },
  }
}

export type WebDoor = ReturnType<typeof createWebDoor>
