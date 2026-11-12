// The timeline of the demo's simulated run: the boards a real run pushes, step by step, over 20 s.
// Pure timers, no file or process: the desktop demo (demo-run.ts, which also writes its postings and
// record) and the screen preview (a scene that plays the whole run) both play it.
import type { Progress } from './ipc'
import type { RunBoard, StepItem, StepRow } from './run-board'

export const STEPS = ['search', 'discover', 'follow', 'collect', 'match'] as const
export const SCRIPT_MS = 20_000

export interface PlayOptions {
  startedAt: string
  /** Steps left out (`find_jobs`'s `skip`): shown as skipped, never played. */
  skip: string[]
  /** Why a step in `skip` is left out, as a real run says it (default `--skip`). */
  reasons?: Record<string, string>
  onBoard: (board: RunBoard) => void
  onProgress?: (p: Progress) => void
  /** How long the whole script takes, in milliseconds (20 s). */
  totalMs?: number
}

/** Plays the run: `ended` resolves when its last step is done (the board still active); `stop` ends it there. */
export function playRun(options: PlayOptions): { ended: Promise<void>; stop: () => void } {
  const { onBoard, startedAt, skip } = options
  const onProgress = options.onProgress ?? (() => undefined)
  const totalMs = options.totalMs ?? SCRIPT_MS
  const scale = totalMs / SCRIPT_MS
  const iso = () => new Date().toISOString()

  const rows: StepRow[] = STEPS.map((name) => ({ name, status: 'waiting', detail: '' }))
  const row = (name: string) => rows.find((r) => r.name === name)!
  let message = 'starting'
  let seq = 0
  const timers: ReturnType<typeof setTimeout>[] = []
  let over = false

  const push = () => onBoard({ active: true, own: true, demo: true, started_at: startedAt, purpose: 'run', message, steps: rows.map((r) => ({ ...r, ...(r.items ? { items: r.items.map((i) => ({ ...i })) } : {}) })) })
  const say = (text: string) => {
    message = text
    seq += 1
    onProgress({ progress: seq, message: text })
  }
  const begin = (name: string, total?: number) => {
    Object.assign(row(name), { status: 'running', started_at: iso(), done: 0, hosts: [] as string[], ...(total ? { total } : {}) })
    say(`${name}: started`)
  }
  const finish = (name: string, detail: string) => {
    const r = row(name)
    Object.assign(r, { status: 'done', detail, finished_at: iso() })
    delete r.total
    say(`${name}: ${detail}`)
  }

  const frames: [number, string, () => void][] = []
  const at = (ms: number, step: string, fn: () => void) => frames.push([ms * scale, step, fn])
  const sites = (name: string, counts: Record<string, number>) => {
    row(name).sites = { ...row(name).sites, ...counts }
  }

  // As in a real run: discover starts first and works beside the others, its sources one after the
  // other; the boards are read at once (`scrape_workers`) and end in whatever order they answer.
  const mark = (name: string, id: string, state: StepItem['state']) => {
    const it = row(name).items?.find((i) => i.id === id)
    if (it) it.state = state
  }
  at(0, 'discover', () => {
    begin('discover')
    Object.assign(row('discover'), { requests: [0, 15], items: [{ id: 'linkedin', name: 'LinkedIn', state: 'running' }] })
  })
  at(1500, 'discover', () => { Object.assign(row('discover'), { request: 'page 4/15', requests: [4, 15] }); say('discover: page 4/15') })
  at(3000, 'discover', () => { Object.assign(row('discover'), { request: 'page 9/15', requests: [9, 15] }); say('discover: page 9/15') })
  at(4500, 'discover', () => { Object.assign(row('discover'), { request: 'page 15/15', requests: [15, 15] }); say('discover: page 15/15') })
  at(4800, 'discover', () => { mark('discover', 'linkedin', 'done'); row('discover').request = '' })
  at(6800, 'discover', () => finish('discover', '6 employers found'))

  // [id, name, postings, when it answers]
  const boards: [string, string, number, number][] = [
    ['jobindex', 'Jobindex', 24, 4500], ['thehub', 'The Hub', 0, 700], ['euraxess', 'EURAXESS', 3, 2600],
    ['globalnyt', 'Globalnyt', 2, 2000], ['jobbank', 'Akademikernes Jobbank', 5, 3900], ['jobmaskinen', 'Jobmaskinen', 4, 3200],
    ['workable', 'Workable', 1, 1500], ['reliefweb', 'ReliefWeb', 0, 1100],
  ]
  at(0, 'search', () => {
    begin('search', boards.length)
    row('search').items = boards.map(([id, name]) => ({ id, name, state: 'waiting' }))
  })
  at(150, 'search', () => { for (const [id] of boards) mark('search', id, 'running'); say('search: reading 8 boards') })
  for (const [id, name, n, ms] of boards) {
    at(ms, 'search', () => {
      mark('search', id, 'done')
      row('search').done = (row('search').done ?? 0) + 1
      if (n) sites('search', { [id]: n })
      say(`${name}: ${n} postings`)
    })
  }
  at(4800, 'search', () => finish('search', '24 postings from 3 boards'))

  at(5000, 'follow', () => begin('follow', 6))
  for (let i = 1; i <= 6; i++) at(5000 + i * 300, 'follow', () => { row('follow').done = i; say(`follow: candidate ${i}/6`) })
  at(7000, 'follow', () => finish('follow', '4 followed, 1 unfollowable'))

  const employers = ['Oceanic Shipping', 'Acme Foods', 'Globex Energy', 'Hooli Software', 'Contoso Retail']
  at(7200, 'collect', () => begin('collect', employers.length))
  employers.forEach((host, i) => {
    at(7400 + i * 1400, 'collect', () => { row('collect').hosts = [host]; say(`collect: reading ${host}`) })
    at(8400 + i * 1400, 'collect', () => {
      const r = row('collect')
      r.done = i + 1
      r.hosts = []
      sites('collect', { [host]: 3 + i })
      say(`collect: ${i + 1}/${employers.length} employers`)
    })
  })
  at(14200, 'collect', () => finish('collect', '5 employers, 25 postings'))

  at(14400, 'match', () => { begin('match'); row('match').phase = 'prefilter'; say('match: prefilter') })
  at(15000, 'match', () => { row('match').phase = 'dedup'; say('match: dedup') })
  at(15400, 'match', () => { Object.assign(row('match'), { phase: '', done: 0, total: 8 }) })
  for (let i = 1; i <= 8; i++) at(15400 + i * 500, 'match', () => { row('match').done = i; say(`match: scored ${i}/8`) })
  at(19600, 'match', () => finish('match', '8 scored, 2 new >= 0.65'))

  for (const name of STEPS) if (skip.includes(name)) Object.assign(row(name), { status: 'skipped', detail: options.reasons?.[name] ?? '--skip' })
  const ended = new Promise<void>((resolve) => {
    push()
    for (const [ms, step, fn] of frames) {
      if (skip.includes(step)) continue
      timers.push(
        setTimeout(() => {
          if (over) return
          fn()
          push()
        }, ms),
      )
    }
    timers.push(
      setTimeout(() => {
        if (over) return
        over = true
        resolve()
      }, totalMs),
    )
  })
  return {
    ended,
    stop: () => {
      over = true
      for (const t of timers) clearTimeout(t)
    },
  }
}
