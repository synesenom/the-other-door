// The renderer's only door to the server: `door:call` forwards one named tool
// (from the generated allow-list) and answers with an envelope, because custom
// error fields do not survive an IPC rejection.
import type { ArchiveFiles } from './archive-files'
import type { PhotoFile } from './photo-file'
import type { ProblemLog } from './problem-log'
import type { ClaudeLogin, LoginState } from './claude-login'
import { copyFile } from 'node:fs/promises'
import { basename, join } from 'node:path'
import tools from '../generated/tools.json'
import { DoorError, type Candidate } from './door-server'
import { isJobId, isMaterialName, materialPath, runRecordPath } from './files'
import { CHANNEL_OPEN } from './notifier'
import { inPlayStatus, needsJob, noticeFor, type Notice, type NoticeEvent } from './notices'
import { type RunBoard } from './run-board'
import { checkUrls, type CvSources } from './cv-sources'
import type { UpdateResult } from './updates'
import { isExternalUrl } from './security'

export const CHANNELS = {
  call: 'door:call',
  openExternal: 'door:open-external',
  progress: 'door:progress',
  saveMaterial: 'door:save-material',
  info: 'door:info',
  stopRun: 'door:stop-run',
  showRun: 'door:show-run',
  /** Pushed to the window: the run that holds the ledger lock (see run-board.ts). */
  runBoard: 'door:run-board',
  currentBoard: 'door:current-board',
  pickCvFiles: 'door:pick-cv-files',
  dropCvFiles: 'door:drop-cv-files',
  draftCv: 'door:draft-cv',
  clearCvSources: 'door:cv-sources-clear',
  /** The CV photo (photo-file.ts): a picture chosen in main, then saved by its token. */
  pickPhoto: 'door:pick-photo',
  savePhoto: 'door:save-photo',
  /** Signing in to Claude (claude-login.ts): start, a pasted code, the page again, cancel, the state now. */
  claudeLoginStart: 'door:claude-login-start',
  claudeLoginCode: 'door:claude-login-code',
  claudeLoginOpen: 'door:claude-login-open',
  claudeLoginCancel: 'door:claude-login-cancel',
  claudeLoginState: 'door:claude-login-state',
  /** Moving the data (archive-files.ts): export to a file chosen in a save dialog; import a picked archive by token. */
  exportData: 'door:export-data',
  pickArchive: 'door:pick-archive',
  importData: 'door:import-data',
  /** Save logs… (#593): the problem report, written where a save dialog says. */
  reportProblem: 'door:report-problem',
  /** Shows the data folder (DOOR_HOME) in the file manager; the window names no path. */
  showHome: 'door:show-home',
  /** Is a newer version out (updates.ts): the cached answer, or a fresh check when asked. */
  checkUpdate: 'door:check-update',
  /** Restart now to install the downloaded update (updates.ts refuses unless one is downloaded). */
  installUpdate: 'door:install-update',
  /** Pushed to the window: the update's state as it changes (index.ts sends it). */
  updateState: 'door:update-state',
  /** Pushed to the window: the sign-in's state as it changes. */
  claudeLogin: 'door:claude-login',
  /** Pushed to the window when a notification is clicked (notifier.ts sends it). */
  open: CHANNEL_OPEN,
} as const

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
// keywords one Haiku call (120 s), setup may install LaTeX or claude.
const TOOL_TIMEOUTS: Record<string, number> = {
  import_posting: 180_000,
  prepare: 180_000,
  revise: 420_000,
  find_jobs: 900_000,
  draft_cv: 960_000,
  keywords: 150_000,
  suggest_titles: 150_000,
  infer_basics: 150_000,
  // setup installs LaTeX or claude, or (a developer action) runs the scraper fixer, tests and a probe.
  setup: 1_800_000,
  // connect_drive waits up to five minutes for the browser; sync_data moves one archive.
  connect_drive: 330_000,
  sync_data: 120_000,
  // phone_start starts door serve and a tunnel, or downloads cloudflared first (issue 444)
  phone_start: 300_000,
  // The CV's two long claude calls, a minute over their own limits (600 s and 900 s), no progress.
  enrich: 660_000,
  // market counts in seconds, but new skill names take one Haiku call.
  market: 180_000,
  // add_company reads the employer's public pages and probes the feed platforms.
  add_company: 180_000,
  // ask: one Haiku call with the read tools (180 s on the server).
  ask: 240_000,
  skill_gaps: 960_000,
  // draft_stories: one sonnet call (300 s on the server), no progress.
  draft_stories: 360_000,
}

// The demo and the onboarding sandbox run on made-up data: none of it may reach the user's Drive.
const DRIVE_TOOLS = new Set(['connect_drive', 'sync_data', 'disconnect_drive'])
const COALESCE_MS = 200

// Tool arguments that name a local file. The window may never send one through `door:call`:
// a file is chosen in a dialog the main process runs and goes by token (cv-sources.ts now;
// export and import in #222). `urls` entries (http or https) are the one thing allowed in `sources`.
// A tool whose parameter could name a file must be here (a test reads tools.json for it).
export const PATH_ARGS: Record<string, { arg: string; urlsOnly?: true }> = {
  draft_cv: { arg: 'sources', urlsOnly: true },
  import_posting: { arg: 'path' },
  export_data: { arg: 'path' },
  import_data: { arg: 'archive' },
  report_problem: { arg: 'path' },
  // the CV photo is chosen in a dialog and saved by token (door:save-photo)
  save_photo: { arg: 'path' },
  // enrich reads web pages; a local file is never one of them.
  enrich: { arg: 'urls', urlsOnly: true },
}

/** Why a call from the window is refused for naming a local file, or null. */
function pathRefusal(tool: string, args: Record<string, unknown>): string | null {
  const rule = PATH_ARGS[tool]
  if (!rule) return null
  const value = args[rule.arg]
  if (value === undefined || value === null) return null
  if (rule.urlsOnly) {
    if (Array.isArray(value) && value.every((v) => isExternalUrl(v))) return null
    return `${tool} takes web addresses only; files are chosen with the file picker.`
  }
  return `${tool} cannot take a file path from the window; files are chosen with a file dialog.`
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

export function registerIpc(
  ipcMain: IpcMainLike,
  server: ServerLike,
  deps: {
    openExternal: (url: string) => Promise<unknown>
    home: string
    /** Save CV / Save letter: a save dialog in front of the window, offered in the Downloads folder. */
    savePdf?: { showSaveDialog: (options: Record<string, unknown>) => Promise<{ canceled: boolean; filePath?: string }>; downloads: string }
    showItemInFolder: (path: string) => void
    /** What the window shows about where its data is: `demo` when it runs on the made-up data. */
    info?: { demo: boolean; sandbox?: 'onboard'; home?: string }
    /** The last run board, for a window that opens (or reloads) while a run is going. */
    currentBoard?: () => RunBoard
    /** Told when a long tool settles (see notices.ts); never allowed to change the answer. */
    notify?: (notice: Notice) => void
    /** The demo only: the simulated `find_jobs`, which nothing in the demo sends to the server. */
    /** The CV files the window may draft from (cv-sources.ts). */
    cvSources?: CvSources
    /** The files of a data move (archive-files.ts). */
    archiveFiles?: Pick<ArchiveFiles, 'exportTarget' | 'pick' | 'take' | 'reportTarget'>
    /** The CV photo's file (photo-file.ts). */
    photoFile?: Pick<PhotoFile, 'pick' | 'take'>
    /** The problem log (problem-log.ts): what the window was refused. */
    problemLog?: ProblemLog
    /** The update check (updates.ts). */
    updates?: { last(): UpdateResult | null; check(): Promise<UpdateResult>; install(): { ok: boolean } }
    /** Signing in to the Claude plan (claude-login.ts). */
    claudeLogin?: Pick<ClaudeLogin, 'start' | 'sendCode' | 'openPage' | 'cancel' | 'state'>
    demoRun?: (args: Record<string, unknown>, onProgress: (p: Progress) => void) => { result: Promise<unknown>; stop: () => void }
  },
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
  ipcMain.handle(CHANNELS.call, async (event, tool: unknown, args: unknown, callId?: unknown): Promise<Envelope> => {
    // A refusal is logged by the tool's name only: what the window sent may be anything.
    const refuse = (error: string): Envelope => {
      deps.problemLog?.write(`refused ${typeof tool === 'string' ? tool.slice(0, 64) : 'a call'}`, error)
      return { ok: false, error }
    }
    if (typeof tool !== 'string' || !ALLOWED.has(tool)) return refuse('unknown tool')
    const refusal = pathRefusal(tool, isPlainObject(args) ? args : {})
    if (refusal) return refuse(refusal)
    if (deps.info?.demo && DRIVE_TOOLS.has(tool)) return refuse('Google Drive is not available on made-up data.')
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
          sender.send(CHANNELS.progress, callId, payload)
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
      const toolArgs = isPlainObject(args) ? args : {}
      if (isRun && deps.demoRun) {
        const run = deps.demoRun(toolArgs, options.onProgress ?? (() => undefined))
        demo = run
        const result = await run.result
        await announce({ kind: 'call', tool, args: toolArgs, result })
        return { ok: true, data: result }
      }
      const result = await server.call(tool, toolArgs, options)
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

  // The CV draft: files come as tokens from the picker, pages as urls; the server gets paths only from here.
  ipcMain.handle(CHANNELS.pickCvFiles, async () => (deps.cvSources ? deps.cvSources.pick() : { files: [], refused: [] }))
  ipcMain.handle(CHANNELS.dropCvFiles, async (_event, paths: unknown) => {
    const strings = Array.isArray(paths) && paths.every((p) => typeof p === 'string')
    return deps.cvSources && strings ? deps.cvSources.add(paths as string[]) : { files: [], refused: [] }
  })
  ipcMain.handle(CHANNELS.clearCvSources, async () => {
    deps.cvSources?.clear()
  })
  ipcMain.handle(CHANNELS.draftCv, async (_event, payload: unknown): Promise<Envelope> => {
    if (!isPlainObject(payload)) return { ok: false, error: 'nothing to draft from' }
    const { files, urls } = payload
    const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === 'string')
    if (!strings(files) || !strings(urls)) return { ok: false, error: 'nothing to draft from' }
    if (files.length + urls.length === 0) return { ok: false, error: 'Add a file or a web page to draft from.' }
    const checked = checkUrls(urls)
    if (!checked.ok) return checked
    let paths: string[] = []
    if (files.length > 0) {
      if (!deps.cvSources) return { ok: false, error: 'files cannot be read here' }
      const resolved = await deps.cvSources.resolve(files)
      if (!resolved.ok) return resolved
      paths = resolved.paths
    }
    try {
      const data = await server.call('draft_cv', { sources: [...paths, ...urls] }, { timeout: TOOL_TIMEOUTS['draft_cv'] })
      return { ok: true, data }
    } catch (e) {
      return failureEnvelope(e)
    }
  })

  // The CV photo: picked in a dialog here, saved by token; the tool gets the real path, the window never names one.
  ipcMain.handle(CHANNELS.pickPhoto, async () => (deps.photoFile ? deps.photoFile.pick() : { error: 'a photo cannot be chosen here' }))
  ipcMain.handle(CHANNELS.savePhoto, async (_event, token: unknown): Promise<Envelope> => {
    const path = typeof token === 'string' ? deps.photoFile?.take(token) : null
    if (!path) return { ok: false, error: 'Choose the picture again.' }
    try {
      return { ok: true, data: await server.call('save_photo', { path }) }
    } catch (e) {
      return failureEnvelope(e)
    }
  })

  // Stop is for a run this app started: its child is ended (the lock dies with it), never a foreign process.
  ipcMain.handle(CHANNELS.stopRun, async (): Promise<{ ok: boolean; error?: string }> => {
    if (demo) demo.stop()
    else if (runs > 0) await server.stop()
    return { ok: true }
  })

  ipcMain.handle(CHANNELS.showRun, async (_event, startedAt: unknown): Promise<{ ok: boolean; error?: string }> => {
    const path = runRecordPath(deps.home, startedAt)
    if (!path) return { ok: false, error: 'that run record is not on disk' }
    deps.showItemInFolder(path)
    return { ok: true }
  })

  // The window only asks: claude's path, folder and page come from doctor and claude, never from the page.
  ipcMain.handle(CHANNELS.claudeLoginStart, async (_event, email: unknown): Promise<{ ok: boolean; error?: string }> => {
    if (!deps.claudeLogin) return { ok: false, error: 'signing in is not available here' }
    await deps.claudeLogin.start(typeof email === 'string' ? email : undefined)
    return { ok: true }
  })
  ipcMain.handle(CHANNELS.claudeLoginCode, async (_event, code: unknown): Promise<{ ok: boolean; error?: string }> =>
    typeof code === 'string' && deps.claudeLogin?.sendCode(code) ? { ok: true } : { ok: false, error: 'That is not a sign-in code.' },
  )
  ipcMain.handle(CHANNELS.claudeLoginOpen, async (): Promise<{ ok: boolean; error?: string }> =>
    (await deps.claudeLogin?.openPage()) ? { ok: true } : { ok: false, error: 'claude has not shown its sign-in page yet' },
  )
  ipcMain.handle(CHANNELS.claudeLoginCancel, async (): Promise<{ ok: boolean }> => {
    deps.claudeLogin?.cancel()
    return { ok: true }
  })
  ipcMain.handle(CHANNELS.claudeLoginState, async (): Promise<LoginState> => deps.claudeLogin?.state() ?? { state: 'idle' })

  // A data move: the file is chosen in main and named by main to the server. The window gets the
  // export's path to show it, and for an import a token; nothing it sends is used as a path.
  const MOVE_TIMEOUT = 180_000
  ipcMain.handle(CHANNELS.exportData, async (): Promise<Envelope | { ok: false; canceled: true }> => {
    if (!deps.archiveFiles) return { ok: false, error: 'exporting is not available here' }
    const target = await deps.archiveFiles.exportTarget()
    if ('canceled' in target) return { ok: false, canceled: true }
    if ('error' in target) return { ok: false, error: target.error }
    try {
      return { ok: true, data: await server.call('export_data', { path: target.path }, { timeout: MOVE_TIMEOUT }) }
    } catch (e) {
      return failureEnvelope(e)
    }
  })
  // Save logs…: the archive goes where the save dialog said; the window names no file.
  ipcMain.handle(CHANNELS.reportProblem, async (): Promise<Envelope | { ok: false; canceled: true }> => {
    if (!deps.archiveFiles) return { ok: false, error: 'reporting is not available here' }
    const target = await deps.archiveFiles.reportTarget()
    if ('canceled' in target) return { ok: false, canceled: true }
    if ('error' in target) return { ok: false, error: target.error }
    try {
      return { ok: true, data: await server.call('report_problem', { path: target.path }, { timeout: 120_000 }) }
    } catch (e) {
      return failureEnvelope(e)
    }
  })
  ipcMain.handle(CHANNELS.pickArchive, async () => (deps.archiveFiles ? deps.archiveFiles.pick() : { error: 'importing is not available here' }))
  ipcMain.handle(CHANNELS.importData, async (_event, token: unknown): Promise<Envelope> => {
    const path = typeof token === 'string' ? deps.archiveFiles?.take(token) : null
    if (!path) return { ok: false, error: 'Choose the archive again.' }
    try {
      return { ok: true, data: await server.call('import_data', { archive: path }, { timeout: MOVE_TIMEOUT }) }
    } catch (e) {
      return failureEnvelope(e)
    }
  })

  ipcMain.handle(CHANNELS.showHome, async (): Promise<{ ok: boolean }> => {
    deps.showItemInFolder(deps.home)
    return { ok: true }
  })

  ipcMain.handle(CHANNELS.checkUpdate, async (_event, fresh?: unknown): Promise<UpdateResult | { enabled: false }> => {
    if (!deps.updates) return { enabled: false }
    if (fresh === true) return deps.updates.check()
    return deps.updates.last() ?? { enabled: false }
  })

  ipcMain.handle(CHANNELS.installUpdate, async (): Promise<{ ok: boolean }> => deps.updates?.install() ?? { ok: false })

  ipcMain.handle(CHANNELS.info, async () => deps.info ?? { demo: false })
  ipcMain.handle(CHANNELS.currentBoard, async (): Promise<RunBoard> => deps.currentBoard?.() ?? { active: false })
  ipcMain.handle(CHANNELS.openExternal, async (_event, url: unknown): Promise<{ ok: boolean; error?: string }> => {
    if (!isExternalUrl(url)) return { ok: false, error: 'only http and https links can be opened' }
    await deps.openExternal(url)
    return { ok: true }
  })

  // A prepared job's files are named by job id and document, never by a path.
  // `sent`: the copy kept when the application was sent (`jobs/output/<id>/sent/`).
  // The window names the job, the document and the name to offer (show's file_names); the path is chosen in the dialog.
  ipcMain.handle(CHANNELS.saveMaterial, async (_event, jobId: unknown, which: unknown, sent: unknown, name: unknown): Promise<{ ok: boolean; path?: string; canceled?: true; error?: string }> => {
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
  })
}
