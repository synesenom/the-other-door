// The renderer's only door to the server: `door:call` forwards one named tool
// (from the generated allow-list) and answers with an envelope, because custom
// error fields do not survive an IPC rejection. Every other capability is one entry of
// `buildActions` (its handler and its type): the preload's `invoke(action)` reaches `door:<action>`,
// and only the channels registered here answer.
import type { ArchiveFiles } from './archive-files'
import type { PhotoFile } from './photo-file'
import type { RememberedCvFile } from './cv-file'
import type { ProblemLog } from './problem-log'
import type { ClaudeLogin, LoginState } from './claude-login'
import { copyFile } from 'node:fs/promises'
import { basename, join } from 'node:path'
import tools from '../generated/tools.json'
import { DoorError, type Candidate } from './door-server'
import { isJobId, isMaterialName, materialPath } from './files'
import { inPlayStatus, needsJob, noticeFor, type Notice, type NoticeEvent, type NoticeTarget } from './notices'
import { type RunBoard } from './run-board'
import { checkUrls, type CvSources, type PickResult } from './cv-sources'
import type { UpdateResult } from './updates'
import type { Environment } from './environments'
import { isExternalUrl } from './security'

/** The two channels that are not actions: `door:call` has its own handler (tokens, PATH_ARGS, progress) and `door:progress` is pushed. */
const CALL_CHANNEL = 'door:call'
const PROGRESS_CHANNEL = 'door:progress'

/** What main pushes to the window, by event name (the channel is `door:<event>`); the preload lists the same four. */
export interface Events {
  /** The run that holds the ledger lock (see run-board.ts). */
  'run-board': RunBoard
  /** The update's state as it changes (index.ts sends it). */
  'update-state': UpdateResult | { enabled: false }
  /** The sign-in's state as it changes. */
  'claude-login': LoginState
  /** A notification was clicked (notifier.ts sends it). */
  open: NoticeTarget
}
export const EVENTS = ['run-board', 'update-state', 'claude-login', 'open'] as const satisfies readonly (keyof Events)[]

/** Pushes one event to a window. */
export function pushEvent<E extends keyof Events>(win: { webContents: { send(channel: string, ...args: unknown[]): void } }, event: E, payload: Events[E]): void {
  win.webContents.send(`door:${event}`, payload)
}

export interface Progress {
  progress: number
  total?: number
  message: string
}

const MAX_CALL_ID = 64
const MAX_MESSAGE = 500

function validCallId(v: unknown): v is string {
  return typeof v === 'string' && v.length > 0 && v.length <= MAX_CALL_ID
}

export type Envelope<T = unknown> =
  | { ok: true; data: T }
  | { ok: false; error: string; candidates?: Candidate[]; stopped?: true; conflict?: true }

interface IpcMainLike {
  handle(channel: string, listener: (event: unknown, ...args: any[]) => unknown): void
}
interface ServerLike {
  call(tool: string, args: Record<string, unknown>, options?: { onProgress?: (p: Progress) => void; timeout?: number }): Promise<unknown>
  /** Ends the child at once (a run the user stopped). */
  stop(): Promise<void>
}

// Call limits longer than the server's default, by tool: the renderer never picks one.
// import_posting fetches a page and has Haiku read and score it; prepare reports
// every 30 s (each report restarts the clock); revise is one Claude call and a
// compile with no progress at all; find_jobs reports all the time, so 15 minutes of silence
// (each report restarts the clock) means it is stuck, and there is no total limit. The
// onboarding wizard's calls: draft_cv is one sonnet call of up to 900 s with no progress,
// keywords one Haiku call (120 s), setup may install Chromium or claude.
const TOOL_TIMEOUTS: Record<string, number> = {
  import_posting: 180_000,
  prepare: 180_000,
  revise: 480_000,
  find_jobs: 900_000,
  draft_cv: 1_260_000,
  // a data move: one archive packed or unpacked.
  export_data: 180_000,
  import_data: 180_000,
  keywords: 150_000,
  suggest_titles: 150_000,
  infer_basics: 300_000, // one read of the CV, asked again once when its answer does not hold (2 x 120 s)
  // setup installs Chromium or claude, which takes a while.
  setup: 1_800_000,
  // connect_drive waits up to five minutes for the browser; sync_data moves one archive.
  connect_drive: 330_000,
  sync_data: 120_000,
  // phone_start starts door serve and a tunnel, or downloads cloudflared first (issue 444)
  phone_start: 300_000,
  // The CV's two long claude calls, a minute over their own limits (the pages' 300 s, then 600 s and 900 s), no progress.
  enrich: 960_000,
  // market counts in seconds, but new skill names take one Haiku call.
  market: 180_000,
  // ask: one Haiku call with the read tools (180 s on the server).
  ask: 240_000,
  // draft_stories: one sonnet call (300 s on the server), no progress.
  draft_stories: 360_000,
}

// Staging and the sandbox run on throwaway data: none of it may reach the user's Drive.
const DRIVE_TOOLS = new Set(['connect_drive', 'sync_data', 'disconnect_drive'])
// ... and none of it may be served to a phone through a public tunnel (stopping and unpairing stay allowed).
const PHONE_SERVING_TOOLS = new Set(['phone_start', 'pair_phone'])
const COALESCE_MS = 200

// Tool arguments that name a local file. The window may never send one through `door:call`:
// a file is chosen in a dialog the main process runs and goes by token (cv-sources.ts, photo-file.ts, archive-files.ts). `urls` entries (http or https) are the one thing allowed in `sources`.
// A tool whose parameter could name a file must be here (a test reads tools.json for it).
// `picked` marks where `door:call` puts the paths of the tokens: all of them in a list, or the one file. `store`
// names a one-shot token store (the photo, an archive) instead of the reusable CV files, `again` what is said when
// its token is not good.
export const PATH_ARGS: Record<string, { arg: string; urlsOnly?: true; picked?: 'list' | 'one'; store?: 'photoFile' | 'archiveFiles'; again?: string }[]> = {
  draft_cv: [{ arg: 'sources', urlsOnly: true, picked: 'list' }],
  import_posting: [{ arg: 'path' }],
  export_data: [{ arg: 'path' }],
  import_data: [{ arg: 'archive', picked: 'one', store: 'archiveFiles', again: 'Choose the archive again.' }],
  report_problem: [{ arg: 'path' }],
  // the CV photo is chosen in a dialog and saved by token
  save_photo: [{ arg: 'path', picked: 'one', store: 'photoFile', again: 'Choose the picture again.' }],
  // enrich reads web pages, and a CV file chosen in a dialog and sent by token
  enrich: [{ arg: 'urls', urlsOnly: true }, { arg: 'files', picked: 'list' }],
}

/** Why a call from the window is refused for naming a local file, or null. */
function pathRefusal(tool: string, args: Record<string, unknown>): string | null {
  for (const rule of PATH_ARGS[tool] ?? []) {
    const value = args[rule.arg]
    if (value === undefined || value === null) continue
    if (rule.urlsOnly) {
      if (Array.isArray(value) && value.every((v) => isExternalUrl(v))) continue
      return `${tool} takes web addresses only; files are chosen with the file picker.`
    }
    return `${tool} cannot take a file path from the window; files are chosen with a file dialog.`
  }
  return null
}

/** The answer of a failed call, in the envelope the window reads (a DoorError keeps its candidates). */
function failureEnvelope(e: unknown): Envelope {
  if (e instanceof DoorError) {
    if (e.stopped) return { ok: false, error: e.message, stopped: true }
    if (e.conflict) return { ok: false, error: e.message, conflict: true }
    return e.candidates ? { ok: false, error: e.message, candidates: e.candidates } : { ok: false, error: e.message }
  }
  return { ok: false, error: e instanceof Error ? e.message : String(e) }
}

const ALLOWED = new Set<string>(tools.map((t) => t.name))

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** The name a save dialog offers: a plain file name ending in .pdf, whatever the window sent. */
function offeredName(name: unknown, which: string): string {
  const plain = typeof name === 'string' ? basename(name.replace(/\\/g, '/')).replace(/[\x00-\x1f]/g, '').trim() : ''
  if (!plain || plain.startsWith('.')) return `${which}.pdf`
  return /\.pdf$/i.test(plain) ? plain : `${plain}.pdf`
}

/** The draft's file sources come back in the order the files were sent: each gets the token it was sent under
 * (the window never sees a path), so the window can name a file it drafted from. */
function withTokens(data: unknown, tokens: string[]): unknown {
  if (!isPlainObject(data) || !Array.isArray(data['sources'])) return data
  let at = 0
  const sources = data['sources'].map((s: unknown) =>
    isPlainObject(s) && s['kind'] === 'file' && at < tokens.length ? { ...s, token: tokens[at++] } : s,
  )
  return { ...data, sources }
}

export interface IpcDeps {
  openExternal: (url: string) => Promise<unknown>
  home: string
  /** Save CV / Save letter: a save dialog in front of the window, offered in the Downloads folder. */
  savePdf?: { showSaveDialog: (options: Record<string, unknown>) => Promise<{ canceled: boolean; filePath?: string }>; downloads: string }
  showItemInFolder: (path: string) => void
  /** Where the window runs (environments.ts) and where its data is. */
  info?: { environment: Environment; home?: string }
  /** The last run board, for a window that opens (or reloads) while a run is going. */
  currentBoard?: () => RunBoard
  /** Told when a long tool settles (see notices.ts); never allowed to change the answer. */
  notify?: (notice: Notice) => void
  /** The sandbox only: the simulated `find_jobs`, which nothing in the sandbox sends to the server. */
  /** The CV files the window may draft from (cv-sources.ts). */
  cvSources?: CvSources
  /** The files of a data move (archive-files.ts). */
  archiveFiles?: Pick<ArchiveFiles, 'exportTarget' | 'pick' | 'take' | 'reportTarget'>
  /** The CV photo's file (photo-file.ts). */
  photoFile?: Pick<PhotoFile, 'pick' | 'take'>
  /** The CV file a draft last read (cv-file.ts). */
  cvFile?: Pick<RememberedCvFile, 'remember' | 'name'>
  /** The problem log (problem-log.ts): what the window was refused. */
  problemLog?: ProblemLog
  /** The update check (updates.ts). */
  updates?: { last(): UpdateResult | null; check(): Promise<UpdateResult>; install(): Promise<{ ok: boolean }> }
  /** Signing in to the Claude plan (claude-login.ts). */
  claudeLogin?: Pick<ClaudeLogin, 'start' | 'sendCode' | 'openPage' | 'cancel' | 'state'>
  demoRun?: (args: Record<string, unknown>, onProgress: (p: Progress) => void) => { result: Promise<unknown>; stop: () => void }
}

/** What `window.door.invoke(action, ...args)` reaches, one entry per action: its handler and, by its parameters and answer, its type
 * (door.d.ts, the phone bridge, the preview and the test stand-in all read its types). A new action is one entry here and nothing else: the phone refuses what is not on its list, the preview answers only what its scenes use, and a screen test gives the action its answer (app/README.md).
 * `door:call` is not here: it keeps its own handler (tokens, PATH_ARGS, progress). */
export function buildActions(deps: IpcDeps, server: ServerLike, state: { runs: () => number; demo: () => { stop: () => void } | null }) {
  return {
    // A link opener.
    'open-external': async (url: string): Promise<{ ok: boolean; error?: string }> => {
      if (!isExternalUrl(url)) return { ok: false, error: 'only http and https links can be opened' }
      await deps.openExternal(url)
      return { ok: true }
    },

    // A prepared job's files are named by job id and document, never by a path.
    // `sent`: the copy kept when the application was sent (`jobs/output/<id>/sent/`).
    // The window names the job, the document and the name to offer (show's file_names); the path is chosen in the dialog.
    'save-material': async (jobId: string, which: 'cv' | 'cover_letter', sent: boolean, name: string): Promise<{ ok: boolean; path?: string; canceled?: true; error?: string }> => {
      if (!isJobId(jobId) || !isMaterialName(which) || typeof sent !== 'boolean') return { ok: false, error: 'unknown document' }
      const source = materialPath(deps.home, jobId, `${which}.pdf`, sent)
      if (!source) return { ok: false, error: 'that PDF is not on disk' }
      if (!deps.savePdf) return { ok: false, error: 'saving is not available here' }
      const r = await deps.savePdf.showSaveDialog({ defaultPath: join(deps.savePdf.downloads, offeredName(name, which)), filters: [{ name: 'PDF', extensions: ['pdf'] }] })
      if (r.canceled || !r.filePath) return { ok: false, canceled: true }
      try {
        await copyFile(source, r.filePath)
      } catch (e) {
        return { ok: false, error: `Could not save it: ${(e as Error).message}` }
      }
      return { ok: true, path: r.filePath }
    },

    // Where the app runs (environments.ts) and where its data is.
    info: async (): Promise<{ environment: Environment; home?: string; remote?: boolean }> => deps.info ?? { environment: 'production' },

    // Stop is for a run this app started: its child is ended (the lock dies with it), never a foreign process.
    'stop-run': async (): Promise<{ ok: boolean; error?: string }> => {
      const demo = state.demo()
      if (demo) demo.stop()
      else if (state.runs() > 0) await server.stop()
      return { ok: true }
    },
    'current-board': async (): Promise<RunBoard> => deps.currentBoard?.() ?? { active: false },

    // The CV files: picked and dropped here, kept under tokens; the server gets paths only from here.
    'pick-cv-files': async (): Promise<PickResult> => (deps.cvSources ? deps.cvSources.pick() : { files: [], refused: [] }),
    'drop-cv-files': async (paths: unknown): Promise<PickResult> => {
      const strings = Array.isArray(paths) && paths.every((p) => typeof p === 'string')
      return deps.cvSources && strings ? deps.cvSources.add(paths as string[]) : { files: [], refused: [] }
    },
    // The CV file: the first file the draft read. Profile → CV's Sources names it.
    'cv-file': async (): Promise<string | null> => (deps.cvFile ? deps.cvFile.name() : null),
    'cv-sources-clear': async (): Promise<void> => {
      deps.cvSources?.clear()
    },
    // The CV photo: picked in a dialog here, saved by token through `door:call`; the tool gets the real path, the window never names one.
    'pick-photo': async (): Promise<{ token: string; name: string } | { canceled: true } | { error: string }> =>
      deps.photoFile ? deps.photoFile.pick() : { error: 'a photo cannot be chosen here' },

    // Signing in to Claude. The window only asks: claude's path, folder and page come from doctor and claude, never from the page.
    'claude-login-start': async (email?: string): Promise<{ ok: boolean; error?: string }> => {
      if (!deps.claudeLogin) return { ok: false, error: 'signing in is not available here' }
      await deps.claudeLogin.start(typeof email === 'string' ? email : undefined)
      return { ok: true }
    },
    'claude-login-code': async (code: string): Promise<{ ok: boolean; error?: string }> =>
      typeof code === 'string' && deps.claudeLogin?.sendCode(code) ? { ok: true } : { ok: false, error: 'That is not a sign-in code.' },
    'claude-login-open': async (): Promise<{ ok: boolean; error?: string }> =>
      (await deps.claudeLogin?.openPage()) ? { ok: true } : { ok: false, error: 'claude has not shown its sign-in page yet' },
    'claude-login-cancel': async (): Promise<{ ok: boolean }> => {
      deps.claudeLogin?.cancel()
      return { ok: true }
    },
    'claude-login-state': async (): Promise<LoginState> => deps.claudeLogin?.state() ?? { state: 'idle' },

    // A data move: the file is chosen in main and named by main to the server. The window gets the
    // export's path to show it, and for an import a token; nothing it sends is used as a path.
    'export-data': async (): Promise<Envelope | { ok: false; canceled: true }> => {
      if (!deps.archiveFiles) return { ok: false, error: 'exporting is not available here' }
      const target = await deps.archiveFiles.exportTarget()
      if ('canceled' in target) return { ok: false, canceled: true }
      if ('error' in target) return { ok: false, error: target.error }
      try {
        return { ok: true, data: await server.call('export_data', { path: target.path }, { timeout: TOOL_TIMEOUTS['export_data'] }) }
      } catch (e) {
        return failureEnvelope(e)
      }
    },
    'pick-archive': async (): Promise<{ token: string; name: string } | { canceled: true } | { error: string }> =>
      deps.archiveFiles ? deps.archiveFiles.pick() : { error: 'importing is not available here' },
    // Save logs…: the archive goes where the save dialog said; the window names no file.
    'report-problem': async (): Promise<Envelope | { ok: false; canceled: true }> => {
      if (!deps.archiveFiles) return { ok: false, error: 'reporting is not available here' }
      const target = await deps.archiveFiles.reportTarget()
      if ('canceled' in target) return { ok: false, canceled: true }
      if ('error' in target) return { ok: false, error: target.error }
      try {
        return { ok: true, data: await server.call('report_problem', { path: target.path }, { timeout: 120_000 }) }
      } catch (e) {
        return failureEnvelope(e)
      }
    },

    // Shows the data folder (DOOR_HOME) in the file manager; the window names no path.
    'show-home': async (): Promise<{ ok: boolean }> => {
      deps.showItemInFolder(deps.home)
      return { ok: true }
    },
    // Is a newer version out (updates.ts): what the app's own checks found; the window never starts one.
    'check-update': async (): Promise<UpdateResult | { enabled: false }> => deps.updates?.last() ?? { enabled: false },
    // Restart now to install the downloaded update (updates.ts refuses unless one is downloaded).
    'install-update': async (): Promise<{ ok: boolean }> => (await deps.updates?.install()) ?? { ok: false },
  } satisfies Record<string, (...args: any[]) => unknown>
}

export type Actions = ReturnType<typeof buildActions>
export type ActionName = keyof Actions
export type ActionArgs<A extends ActionName> = Parameters<Actions[A]>
export type ActionResult<A extends ActionName> = Awaited<ReturnType<Actions[A]>>

export function registerIpc(
  ipcMain: IpcMainLike,
  server: ServerLike,
  deps: IpcDeps,
): void {
  // A settled call may deserve a notification. The job's words come from one `show` call here, in
  // the main process, so a reloaded window cannot lose them. Nothing in it can fail the call.
  const announce = async (event: NoticeEvent): Promise<void> => {
    if (!deps.notify) return
    try {
      let full = event
      if (needsJob(event) && event.kind !== 'foreign-run-ended') {
        const id = (event.kind === 'call' && isPlainObject(event.result) && event.result['job_id']) || event.args['job_id']
        try {
          const posting = await server.call('show', { job_id: id })
          if (isPlainObject(posting) && typeof posting['title'] === 'string' && typeof posting['company'] === 'string') {
            full = { ...event, job: { title: posting['title'], company: posting['company'], inPlay: inPlayStatus(String(posting['status'] ?? '')) } }
          }
        } catch {
          // no words: the notice is plainer
        }
      }
      const notice = noticeFor(full)
      if (notice) deps.notify(notice)
    } catch {
      // a notification is a courtesy
    }
  }
  let runs = 0 // find_jobs calls in flight
  let demo: { stop: () => void } | null = null
  const actions = buildActions(deps, server, { runs: () => runs, demo: () => demo })
  // A refusal is logged by the tool's name only: what the window sent may be anything.
  const refused = (tool: unknown, error: string): Envelope => {
    deps.problemLog?.write(`refused ${typeof tool === 'string' ? tool.slice(0, 64) : 'a call'}`, error)
    return { ok: false, error }
  }
  // The CV file: the first file the draft read. Profile → CV's Sources names it.
  const rememberCvFile = async (data: unknown): Promise<void> => {
    if (!deps.cvFile || !isPlainObject(data) || !Array.isArray(data['sources'])) return
    const file = data['sources'].find((s: unknown) => isPlainObject(s) && s['kind'] === 'file' && typeof s['source'] === 'string') as { source: string } | undefined
    if (file) await deps.cvFile.remember(file.source)
  }
  ipcMain.handle(CALL_CHANNEL, async (event, tool: unknown, args: unknown, callId?: unknown, tokens?: unknown): Promise<Envelope> => {
    const refuse = (error: string) => refused(tool, error)
    if (typeof tool !== 'string' || !ALLOWED.has(tool)) return refuse('unknown tool')
    const refusal = pathRefusal(tool, isPlainObject(args) ? args : {})
    if (refusal) return refuse(refusal)
    if (deps.info && deps.info.environment !== 'production' && DRIVE_TOOLS.has(tool)) return refuse('Google Drive is not available in staging or the sandbox.')
    if (deps.info && deps.info.environment !== 'production' && PHONE_SERVING_TOOLS.has(tool)) return refuse('Your phone is not available in staging or the sandbox.')
    // Picked files come as tokens (draft_cv, enrich: reusable CV-file tokens; save_photo, import_data: one-shot
    // tokens of their own store; their `picked` PATH_ARGS rule): the paths go into that rule's argument, the window never names one.
    let toolArgs = isPlainObject(args) ? args : {}
    let paths: string[] = []
    if (tokens !== undefined) {
      const rule = PATH_ARGS[tool]?.find((r) => r.picked)
      if (!rule) return refuse('unknown tool')
      if (rule.store) {
        // one file, one use
        const path = Array.isArray(tokens) && tokens.length === 1 && typeof tokens[0] === 'string' ? deps[rule.store]?.take(tokens[0]) : null
        if (!path) return { ok: false, error: rule.again! }
        toolArgs = { ...toolArgs, [rule.arg]: path }
      } else {
        // only a draft may go without a file (it reads pages)
        if (!Array.isArray(tokens) || !tokens.every((t) => typeof t === 'string') || (tokens.length === 0 && tool !== 'draft_cv')) return { ok: false, error: 'Choose the file again.' }
        if (tool === 'draft_cv') {
          const urls = toolArgs['sources'] ?? []
          if (!Array.isArray(urls)) return { ok: false, error: 'nothing to draft from' }
          if (tokens.length + urls.length === 0) return { ok: false, error: 'Add a file or a web page to draft from.' }
          const checked = checkUrls(urls)
          if (!checked.ok) return checked
        }
        if (tokens.length > 0) {
          if (!deps.cvSources) return { ok: false, error: 'files cannot be read here' }
          const resolved = await deps.cvSources.resolve(tokens)
          if (!resolved.ok) return resolved
          paths = resolved.paths
        }
        const own = toolArgs[rule.arg]
        toolArgs = { ...toolArgs, [rule.arg]: [...paths, ...(Array.isArray(own) ? own : [])] }
      }
    }
    const sender = (event as { sender?: { send(channel: string, ...a: unknown[]): void } } | undefined)?.sender
    const options: { onProgress?: (p: Progress) => void; timeout?: number } = {}
    if (tool in TOOL_TIMEOUTS) options.timeout = TOOL_TIMEOUTS[tool]
    let flush = () => {}
    if (sender && validCallId(callId)) {
      // The tools report in bursts (a posting at a time): at most one message per 200 ms
      // reaches the window, the latest, and what is pending goes out when the call ends.
      let pending: Progress | null = null
      let timer: ReturnType<typeof setTimeout> | null = null
      const send = () => {
        timer = null
        if (!pending) return
        const payload = pending
        pending = null
        try {
          sender.send(PROGRESS_CHANNEL, callId, payload)
        } catch {
          // the window went away; the call carries on
        }
      }
      options.onProgress = (p) => {
        pending = { progress: p.progress, message: String(p.message ?? '').slice(0, MAX_MESSAGE), ...(p.total !== undefined ? { total: p.total } : {}) }
        timer ??= setTimeout(send, COALESCE_MS)
      }
      flush = () => {
        if (timer) clearTimeout(timer)
        send()
      }
    }
    const isRun = tool === 'find_jobs'
    if (isRun) runs += 1
    try {
      if (isRun && deps.demoRun) {
        const run = deps.demoRun(toolArgs, options.onProgress ?? (() => undefined))
        demo = run
        const result = await run.result
        await announce({ kind: 'call', tool, args: toolArgs, result })
        return { ok: true, data: result }
      }
      let result = await server.call(tool, toolArgs, options)
      if (Array.isArray(tokens)) {
        if (tool === 'draft_cv') {
          await rememberCvFile(result)
          result = withTokens(result, tokens as string[])
        } else if (tool === 'enrich') await deps.cvFile?.remember(paths[0]!) // a newer CV file is the CV file from then on
      }
      await announce({ kind: 'call', tool, args: toolArgs, result })
      return { ok: true, data: result }
    } catch (e) {
      const failure = {
        kind: 'call-error' as const,
        tool,
        args: isPlainObject(args) ? args : {},
        error: {
          message: e instanceof Error ? e.message : String(e),
          ...(e instanceof DoorError && e.timedOut ? { timedOut: true } : {}),
          ...(e instanceof DoorError && e.stopped ? { stopped: true } : {}),
        },
      }
      await announce(failure)
      if (e instanceof DoorError) {
        if (isRun && e.timedOut) {
          // the child may still hold the lock: end it rather than leave it running unseen
          await server.stop().catch(() => undefined)
          return { ok: false, error: 'The run stopped: The other door heard nothing for 15 minutes.' }
        }
      }
      return failureEnvelope(e)
    } finally {
      if (isRun) {
        runs -= 1
        demo = null
      }
      flush()
    }
  })

  // Every other action is one entry of `buildActions`; a name not in it has no handler, so Electron refuses it.
  for (const [name, handler] of Object.entries(actions) as [string, (...args: any[]) => unknown][]) ipcMain.handle(`door:${name}`, (_event, ...args) => handler(...args))
}
