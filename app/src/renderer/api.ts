// The renderer's side of window.door. The tools return plain JSON that the
// server's schema does not describe (no outputSchema), so these result types are
// written by hand from src/door/commands/{matches,status}.py; a changed field
// there is not caught by tools.json.
import type { Envelope } from '../main/ipc'
import type { NoticeTarget } from '../main/notices'
import type { RunBoard, StepActivity, StepRow } from '../main/run-board'

export type { NoticeTarget, RunBoard, StepActivity, StepRow }

export interface Candidate {
  job_id: string
  title: string
  company: string
  status: string
}

export class ApiError extends Error {
  candidates?: Candidate[]
  /** The call was ended on purpose (Stop). */
  stopped?: boolean
  /** Drive and this computer both changed (sync_data): ask which side to keep. */
  conflict?: boolean
  constructor(message: string, candidates?: Candidate[], stopped?: boolean, conflict?: boolean) {
    super(message)
    this.name = 'ApiError'
    this.candidates = candidates
    if (stopped) this.stopped = true
    if (conflict) this.conflict = true
  }
}

export interface SiteFailure {
  site: string
  outcome: string
  errors?: string[]
}

export interface InProgress {
  purpose?: string
  message: string
  done?: number | null
  total?: number | null
  site?: string | null
  stage?: string | null
  [key: string]: unknown
}

export interface StatusSummary {
  min_score: number
  since_last_review: {
    last_reviewed_at: string | null
    runs: number
    last_run?: { finished_at?: string | null } | null
    new_matches: number
    site_failures: SiteFailure[]
  }
  in_progress: InProgress | null
  /** Google Drive sync (never the tokens); `configured` is false in a build without the Google client. */
  drive?: { connected: boolean; account: string | null; last_synced: string | null; last_error: string | null; configured?: boolean }
  /** Something keeps going wrong since the last problem report (a site, scoring, the server, a tool): no details. */
  recurring_problem?: boolean
}

/** One site's outcome in a run record (`core/runs.site_entries`). */
export interface SiteOutcome {
  site: string
  outcome: string
  count?: number
  errors?: string[]
  warning?: string
  until?: string
}

/** The record `find_jobs` returns (written by src/door/commands/find.py), the parts the summary reads. */
export interface RunRecord {
  started_at: string
  finished_at: string
  elapsed_s: number
  steps: string[]
  skipped: Record<string, string>
  search: { sites?: SiteOutcome[] } | null
  collect: { sites?: SiteOutcome[] } | null
  match: { failed?: string[]; scored?: number; above_threshold?: number; unscored_before?: number; min_score?: number } | null
  new_above_threshold: string[]
  top: { id: string; score: number; title: string; company: string }[]
  failures: string[]
}

export type RunOutcome =
  | { kind: 'done'; record: RunRecord }
  /** Something else holds the ledger lock (a terminal, Claude Code); `started` is its clock time. */
  | { kind: 'busy' }
  /** The app's own Prepare is running: find_jobs and prepare share one slot. */
  | { kind: 'preparing' }
  | { kind: 'stopped' }
  | { kind: 'error'; message: string }

/**
 * The whole pipeline (`find_jobs`). It always asks for
 * progress: that is what restarts the call's idle limit. `onLine` gets the text of each event.
 * `skip` names the steps to leave out (the first run of the onboarding skips all but search and match).
 */
export async function findJobs(options: { skip?: string[]; onLine?: (line: string) => void } = {}): Promise<RunOutcome> {
  const skip = options.skip ?? []
  try {
    const record = await call<RunRecord>('find_jobs', skip.length > 0 ? { skip } : {}, {
      onProgress: (p) => options.onLine?.(p.message),
    })
    return { kind: 'done', record }
  } catch (e) {
    if (e instanceof ApiError && e.stopped) return { kind: 'stopped' }
    const text = errorText(e)
    if (/another long-running tool/.test(text)) return { kind: 'preparing' }
    if (/is in progress/.test(text)) return { kind: 'busy' }
    return { kind: 'error', message: text }
  }
}

export function stopRun(): Promise<{ ok: boolean; error?: string }> {
  return window.door.stopRun()
}

/** Reveals the run record of the run that started at `startedAt` (the main process maps it to the file). */
export function showRun(startedAt: string): Promise<{ ok: boolean; error?: string }> {
  return window.door.showRun(startedAt)
}

export function runBoard(): Promise<RunBoard> {
  return window.door.runBoard()
}

/** Calls `cb` with each new run board the main process pushes; returns the unsubscribe. */
export function onRunBoard(cb: (board: RunBoard) => void): () => void {
  return window.door.onRunBoard(cb)
}

/** A clicked notification that names a job, handed to the screen that holds it (`n` tells two clicks apart). */
export interface Opening {
  target: Extract<NoticeTarget, { jobId: string }>
  n: number
}

/** Calls `cb` with the target of each clicked notification; returns the unsubscribe. */
export function onOpen(cb: (target: NoticeTarget) => void): () => void {
  return window.door.onOpen(cb)
}

export interface Match {
  id: string
  score: number | null
  title: string
  title_en: string | null
  company: string
  location: string
  status: string
  is_new: boolean
  /** When the status last changed (a tracked job), else null. */
  updated_at?: string | null
  /** The interview rounds so far, each passed, still pending, or how it ended. */
  rounds?: { stage: string; result: string }[]
}

export interface MatchesResult {
  min_score: number
  last_reviewed_at: string | null
  /** How many postings the model scored (above 0), whatever the bar. */
  scored?: number
  matches: Match[]
  /** Until a posting first reached the bar: the best few below it and what would widen the search; null otherwise. */
  weak?: { matches: Match[]; hint: 'sources' | 'keywords'; sources: { key: string; label: string }[] } | null
}

/** `show`'s `materials`: null until both PDFs exist. Paths are absolute; the page lists may hold stale images past `page_counts`. */
export interface Materials {
  output_dir: string
  pdfs: { cv: string; cover_letter: string }
  pngs: { cv: string[]; cover_letter: string[] }
  keywords: string[]
  tailoring: string[]
  page_counts: { cv: number; cover_letter: number }
  cover_letter_words: number | null
  rendered: boolean
  /** The application went out: these are the files as sent (`jobs/output/<id>/sent/`), not to be revised. */
  sent?: boolean
  /** What to save each PDF as: the candidate's name first (`show`'s file_names). */
  file_names: { cv: string; cover_letter: string }
  /** The numbers, employers, skills… of the CV and letter that cv.md and the story bank do not back; null when not checked. */
  unsupported?: { kind: string; value: string; context: string; file: string }[] | null
}

export type Document = 'cv' | 'cover_letter'

export interface PrepareResult {
  job_id: string | null
  outcome: 'prepared' | 'skipped' | 'no_matches' | 'failed'
  output_dir?: string
  files?: string[]
  regenerated_incomplete?: boolean
}

export interface ReviseResult {
  outcome: 'revised' | 'undone'
  job_id: string
  file: string
  backup?: string
  compile?: { file: string; status: 'compiled' | 'skipped' | 'error'; stderr?: string }[]
}

export interface Posting {
  id: string
  title: string
  title_en?: string | null
  company: string
  location?: string
  url?: string
  /** The employer's own application page, when the board's ad links to one (LinkedIn, Jobindex…). */
  apply_url?: string | null
  description?: string
  score?: number | null
  score_reason?: string | null
  posted_at?: string | null
  source?: string | null
  /** The site in words ("Jobindex"); null when there is nothing to name. */
  source_name?: string | null
  language?: string
  language_requirement?: 'required' | 'advantage' | 'none' | null
  matching_skills?: string[]
  missing_skills?: string[]
  status: string
  materials?: Materials | null
  /** The salary estimate `prepare` saved; null until there is one. `show` never asks for it. */
  salary?: Salary | null
}

/** A salary estimate from public pages (`salary_estimate`'s fields), adjusted to the CV's experience. */
export interface Salary {
  low: number
  high: number
  /** Its three-letter code: DKK, EUR, GBP… */
  currency: string
  period: 'month' | 'year'
  gross: boolean
  /** Where the candidate sits in the market range for this job. */
  position: 'below' | 'within' | 'above' | null
  basis: string
  sources: { title: string; url: string }[]
  /** The ad's own figure as written, when it states one (the range is then that figure). */
  ad_salary: string | null
  as_of: string
}

export interface SetStatusResult {
  job_id: string
  status: string
  notes?: string
  current?: string
  sent_dir?: string
  warning?: string
}

export interface ImportResult {
  job_id: string
  path?: string
  replaced?: boolean
  score: number | null
  score_reason: string | null
  score_error?: string
}

/** The statuses a person can choose, in words. "Interview" is a group: its value is not a ledger status. */
export const STATUSES = [
  { value: 'unapplied', word: 'Not yet applied' },
  { value: 'prepared', word: 'Prepared' },
  { value: 'applied', word: 'Applied' },
  { value: 'interview', word: 'Interview' },
  { value: 'ghosted', word: 'Ghosted' },
  { value: 'rejected', word: 'Rejected' },
  { value: 'offer', word: 'Offer' },
  { value: 'discarded', word: 'Not for me' },
] as const

export const INTERVIEW_KINDS = [
  { value: 'interview:screening', word: 'Screening', meaning: 'A pre-screening or recruiter call' },
  { value: 'interview:impression', word: 'First impression', meaning: 'The first non-technical interview' },
  { value: 'interview:assessment', word: 'Assessment', meaning: 'A personality or cognitive test' },
  { value: 'interview:technical', word: 'Technical', meaning: 'A technical interview, case or take-home' },
] as const

/** Calls one tool; a failed call throws an ApiError carrying the server's own words. */
export async function call<T>(
  tool: string,
  args: Record<string, unknown> = {},
  options: { onProgress?: (p: ProgressEvent) => void } = {},
): Promise<T> {
  const { onProgress } = options
  const callId = onProgress ? newCallId() : undefined
  const unsubscribe = onProgress && callId ? window.door.onProgress(callId, onProgress) : undefined
  try {
    const r: Envelope<T> = (await (callId ? window.door.call(tool, args, callId) : window.door.call(tool, args))) as Envelope<T>
    if (!r.ok) throw new ApiError(r.error, r.candidates, r.stopped, r.conflict)
    return r.data
  } finally {
    unsubscribe?.()
  }
}

/** What `draft_cv` answers (src/door/commands/cv.py `_draft_cv_core`). */
export interface CvDraft {
  markdown: string
  sources: { source: string; kind: 'file' | 'url'; chars?: number }[]
  provenance: { source: string; contributed: string }[]
  todos: string[]
}

/** A CV draft from picked files (tokens) and web pages; the window never names a path, so this has its own channel. */
export async function draftCv(payload: { files: string[]; urls: string[] }): Promise<CvDraft> {
  const r = (await window.door.draftCv(payload)) as Envelope<CvDraft>
  if (!r.ok) throw new ApiError(r.error, r.candidates, r.stopped, r.conflict)
  return r.data
}

// status_summary is the slow call and several parts of a screen want it at once:
// they share the call in flight; once it settles, the next caller asks afresh. The
// call is kept with the bridge it went through, so a new window.door never gets
// an answer from the old one.
let summaryInFlight: { bridge: unknown; promise: Promise<StatusSummary> } | null = null

/** `status_summary`, one call however many ask at the same time. */
export function statusSummary(): Promise<StatusSummary> {
  const bridge = window.door
  if (summaryInFlight?.bridge !== bridge) {
    const entry = {
      bridge,
      promise: call<StatusSummary>('status_summary').finally(() => {
        if (summaryInFlight === entry) summaryInFlight = null
      }),
    }
    summaryInFlight = entry
  }
  return (summaryInFlight as { promise: Promise<StatusSummary> }).promise
}

export interface ProgressEvent {
  progress: number
  total?: number
  message: string
}

let callCounter = 0
function newCallId(): string {
  callCounter += 1
  return `c${Date.now().toString(36)}-${callCounter}`
}

export function openExternal(url: string): Promise<{ ok: boolean; error?: string }> {
  return window.door.openExternal(url)
}

export function saveMaterial(jobId: string, which: Document, sent: boolean, name: string): Promise<{ ok: boolean; path?: string; canceled?: true; error?: string }> {
  return window.door.saveMaterial(jobId, which, sent, name)
}

const base = (path: string) => path.split(/[\\/]/).filter(Boolean).pop() ?? ''

/** The door-file address of a page image: job and file name only (`sent/` for the copy sent), `v` defeats the image cache after a revision. */
export function materialUrl(jobId: string, pngPath: string, v: number, sent = false): string {
  if (window.door.pageUrl) return window.door.pageUrl(jobId, pngPath, v, sent) // the phone app: /files over door serve
  return `door-file://output/${encodeURIComponent(jobId)}/${sent ? 'sent/' : ''}${encodeURIComponent(base(pngPath))}?v=${v}`
}

/** The page images that belong to the document now (a shorter revision leaves old ones on disk). */
export function visiblePages(m: Materials, which: Document): string[] {
  return m.pngs[which].slice(0, m.page_counts[which])
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

const STATUS_WORDS: Record<string, string> = {
  prepared: 'Prepared',
  applied: 'Applied',
  ghosted: 'Ghosted',
  rejected: 'Rejected',
  offer: 'Offer',
  discarded: 'Discarded',
}

/** A ledger status as words; nothing for a posting nobody has acted on. */
export function statusWord(status: string): string | null {
  if (!status || status === 'unapplied') return null
  if (status.startsWith('interview:')) return `Interview: ${status.slice('interview:'.length)}`
  return STATUS_WORDS[status] ?? status
}

export const placeLine = (company: string, location?: string) => (location ? `${company} · ${location}` : company)
export const scoreText = (score: number | null | undefined) => (typeof score === 'number' ? score.toFixed(2) : '')

/** "Danish — required": the ad's language in English, and what it asks of you. */
export function languageLine(code: string, requirement?: string | null): string {
  let name = code
  try {
    name = new Intl.DisplayNames(['en'], { type: 'language' }).of(code) ?? code
  } catch {
    // an unknown code stays as written
  }
  if (requirement === 'required') return `${name} — required`
  if (requirement === 'advantage') return `${name} — an advantage`
  return name
}

