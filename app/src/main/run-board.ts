// What the Finding jobs screen draws from: the run that holds The other door's ledger lock, read from
// `jobs/.lock.json` (who) and `jobs/.progress.json` (what it is doing, with the folded `steps`
// the server writes). Pure fold plus a watcher; only file access, no process is started.
import { readFileSync, watch, type FSWatcher } from 'node:fs'
import { join } from 'node:path'

export interface StepRow {
  name: string
  status: 'waiting' | 'running' | 'done' | 'failed' | 'skipped'
  detail: string
  started_at?: string
  finished_at?: string
  done?: number
  total?: number
  sites?: Record<string, number>
  hosts?: string[]
  phase?: string
  request?: string
  requests?: [number, number]
  /** The boards or sources a step reads, each with how far it got. */
  items?: StepItem[]
}

export interface StepItem {
  /** The board's or source's key (`jobindex`, `linkedin`); `name` is how it is shown. */
  id: string
  name: string
  state: 'waiting' | 'running' | 'done' | 'failed'
  /** What a running board is doing: searching keyword N of M, or reading ad N of a keyword's M. */
  activity?: StepActivity
}

export interface StepActivity {
  kind: 'searching' | 'reading'
  keyword: string
  done: number
  total: number
}

export type RunBoard =
  | { active: false }
  | {
      active: true
      /** The run was started by this app's own server (so Stop may end it). */
      own: boolean
      started_at: string
      purpose: string
      message: string
      steps: StepRow[]
      /** The simulated run of the demo. */
      demo?: boolean
    }

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

export function processAlive(pid: number): boolean {
  try {
    process.kill(pid, 0)
    return true
  } catch (e) {
    return (e as NodeJS.ErrnoException).code === 'EPERM'
  }
}

function steps(v: unknown): StepRow[] {
  if (!Array.isArray(v)) return []
  return v.filter((s): s is StepRow => isObject(s) && typeof s.name === 'string' && typeof s.status === 'string')
}

/** The board of a lock holder: active only while the process named in `.lock.json` is alive. */
export function foldBoard(
  progress: unknown,
  lock: unknown,
  alive: (pid: number) => boolean = processAlive,
  ownPid: () => number | null = () => null,
): RunBoard {
  if (!isObject(lock) || !isObject(progress)) return { active: false }
  const pid = lock['pid']
  if (typeof pid !== 'number' || !alive(pid)) return { active: false }
  return {
    active: true,
    own: ownPid() === pid,
    started_at: typeof lock['started_at'] === 'string' ? lock['started_at'] : '',
    purpose: typeof lock['purpose'] === 'string' ? lock['purpose'] : '',
    message: typeof progress['message'] === 'string' ? progress['message'] : '',
    steps: steps(progress['steps']),
  }
}

function readJson(path: string): unknown {
  try {
    return JSON.parse(readFileSync(path, 'utf8'))
  } catch {
    return null
  }
}

export interface WatchOptions {
  ownPid?: () => number | null
  alive?: (pid: number) => boolean
  debounceMs?: number
  pollMs?: number
}

/** Calls `onBoard` with each new board of the run in `<home>/jobs`: a file watch, debounced, and a poll for the platforms where it misses. */
export function watchRunBoard(home: string, onBoard: (board: RunBoard) => void, options: WatchOptions = {}) {
  const dir = join(home, 'jobs')
  const { debounceMs = 100, pollMs = 1000, alive = processAlive, ownPid } = options
  let last: RunBoard = { active: false }
  let stopped = false
  let watcher: FSWatcher | null = null
  let timer: ReturnType<typeof setTimeout> | null = null

  const check = () => {
    if (stopped) return
    const board = foldBoard(readJson(join(dir, '.progress.json')), readJson(join(dir, '.lock.json')), alive, ownPid)
    if (JSON.stringify(board) === JSON.stringify(last)) return
    last = board
    onBoard(board)
  }
  const soon = () => {
    if (timer) return
    timer = setTimeout(() => {
      timer = null
      check()
    }, debounceMs)
  }
  const attach = () => {
    if (watcher || stopped) return
    try {
      watcher = watch(dir, soon)
      watcher.on('error', () => {
        watcher?.close()
        watcher = null
      })
    } catch {
      watcher = null // no jobs folder yet: the poll tries again
    }
  }

  attach()
  check()
  const poll = setInterval(() => {
    attach()
    check()
  }, pollMs)

  return {
    current: (): RunBoard => last,
    stop: () => {
      stopped = true
      clearInterval(poll)
      if (timer) clearTimeout(timer)
      watcher?.close()
      watcher = null
    },
  }
}
