// The simulated run of the demo (`npm run dev:demo`): "Find new jobs" there plays a scripted
// sequence instead of calling `find_jobs`, so nothing reaches the network or your Claude plan.
// It pushes the same boards a real run does, writes two made-up postings into the demo's
// jobs/ folder and answers with a run record of the real shape. Only file writes and timers.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { DoorError } from './door-server'
import type { Progress } from './ipc'
import type { RunBoard } from './run-board'
import { playRun, SCRIPT_MS, STEPS } from './demo-script'

const MIN_SCORE = 0.65

export interface DemoSite {
  site: string
  outcome: 'ok' | 'empty' | 'resting' | 'failed'
  count: number
  until?: string
  warning?: string
}

export interface DemoRunRecord {
  started_at: string
  finished_at: string
  elapsed_s: number
  steps: string[]
  skipped: Record<string, string>
  search: { sites: DemoSite[]; postings: number; summary: string; elapsed_s: number } | null
  discover: { summary: string; elapsed_s: number } | null
  follow: { summary: string; elapsed_s: number } | null
  collect: { sites: DemoSite[]; postings: number; summary: string; elapsed_s: number } | null
  match: { scored: number; unscored_before: number; failed: string[]; new_above_threshold: string[]; top: Top[]; summary: string; elapsed_s: number } | null
  new_above_threshold: string[]
  top: Top[]
  failures: string[]
}

interface Top {
  id: string
  score: number
  title: string
  company: string
}

const NEW_JOBS = [
  {
    id: 'jobindex.demo-new-1', site: 'jobindex', title: 'Finance Controller', company: 'Tyrell Maritime', location: 'København', score: 0.86,
    score_reason: 'Controller role with IFRS reporting and a monthly close, both central in the CV.',
    matching_skills: ['IFRS', 'month-end close'], missing_skills: ['shipping'], language: 'en', language_requirement: 'none',
    description: 'Tyrell Maritime is looking for a Finance Controller to own the monthly close and the group reporting.\n\nYou will work with the business on forecasts and keep the numbers in line with IFRS.',
  },
  {
    id: 'greenhouse.demo-new-2', site: 'greenhouse', title: 'Senior Business Controller', company: 'Wonka Pharma', location: 'Hillerød', score: 0.73,
    score_reason: 'Business controlling for a pharma site; budgeting matches, the sector is new.',
    matching_skills: ['budgeting', 'forecasting'], missing_skills: ['GxP'], language: 'en', language_requirement: 'none',
    description: 'Wonka Pharma needs a Senior Business Controller for its manufacturing site.\n\nYou own the budget cycle, the forecasts and the investment cases.',
  },
]

export interface DemoRunOptions {
  /** The `find_jobs` arguments: only `skip` is honoured. */
  args?: Record<string, unknown>
  onBoard: (board: RunBoard) => void
  onProgress: (p: Progress) => void
  /** How long the whole script takes, in milliseconds (20 s). */
  totalMs?: number
}

/**
 * As a real run: when the demo profile sets discovery sources and every one is off, Discover is skipped
 * with `discover`'s reason ("linkedin_discovery is off; …"); null when one is on or none is set.
 */
function discoveryOff(demoDir: string): string | null {
  let config: Record<string, unknown>
  try {
    config = JSON.parse(readFileSync(join(demoDir, 'profile', 'config.json'), 'utf8')) as Record<string, unknown>
  } catch {
    return null
  }
  const keys = Object.keys(config).filter((k) => k.endsWith('_discovery'))
  if (keys.length === 0 || keys.some((k) => config[k] !== false)) return null
  return keys.map((k) => `${k} is off`).join('; ')
}

/** Same rule as `_run_record_filename` in src/door/commands/find.py. */
const recordName = (startedAt: string) => `${startedAt.replace(/[^A-Za-z0-9_-]/g, '-')}.json`

export function startDemoRun(demoDir: string, options: DemoRunOptions): { result: Promise<DemoRunRecord>; stop: () => void } {
  const { onBoard, onProgress } = options
  const totalMs = options.totalMs ?? SCRIPT_MS
  const skip = Array.isArray(options.args?.['skip']) ? (options.args['skip'] as unknown[]).map(String) : []
  const reasons: Record<string, string> = Object.fromEntries(skip.map((name) => [name, '--skip']))
  const off = discoveryOff(demoDir)
  if (off && !skip.includes('discover')) {
    skip.push('discover')
    reasons['discover'] = off
  }
  const startedAt = new Date().toISOString()

  const play = playRun({ startedAt, skip, reasons, onBoard, onProgress, totalMs })
  let over = false
  let fail: (e: Error) => void = () => undefined
  const result = new Promise<DemoRunRecord>((resolve, rej) => {
    fail = rej
    const skipped: Record<string, string> = Object.fromEntries(STEPS.filter((name) => skip.includes(name)).map((name) => [name, reasons[name]]))
    void play.ended.then(() => {
      if (over) return
      over = true
      const record = write(demoDir, startedAt, totalMs, skipped)
      onBoard({ active: false })
      resolve(record)
    })
  })
  return {
    result,
    stop: () => {
      if (over) return
      over = true
      play.stop()
      onBoard({ active: false })
      fail(Object.assign(new DoorError('stopped'), { stopped: true as const }))
    },
  }
}

function write(demoDir: string, startedAt: string, totalMs: number, skipped: Record<string, string>): DemoRunRecord {
  for (const job of NEW_JOBS) {
    const dir = join(demoDir, 'jobs', 'postings', startedAt.slice(0, 10), job.site)
    mkdirSync(dir, { recursive: true })
    const { site, ...fields } = job
    const posting = { ...fields, url: `https://example.com/jobs/${job.id}`, posted_at: startedAt, scraped_at: startedAt, source: site }
    writeFileSync(join(dir, `${job.id}.json`), JSON.stringify(posting, null, 2))
  }
  const top: Top[] = NEW_JOBS.map((j) => ({ id: j.id, score: j.score, title: j.title, company: j.company }))
  const ids = top.map((t) => t.id)
  const took = (ms: number) => (ms * (totalMs / SCRIPT_MS)) / 1000
  const ran = STEPS.filter((s) => !(s in skipped))
  const until = new Date(Date.parse(startedAt) + 24 * 3_600_000).toISOString()
  const record: DemoRunRecord = {
    started_at: startedAt,
    finished_at: new Date(Date.parse(startedAt) + totalMs).toISOString(),
    elapsed_s: totalMs / 1000,
    steps: ran,
    skipped,
    search: ran.includes('search')
      ? {
          sites: [
            { site: 'jobindex', outcome: 'ok', count: 24 },
            { site: 'thehub', outcome: 'empty', count: 0, warning: 'returned nothing: the site may have changed' },
            { site: 'jobbank', outcome: 'resting', count: 0, until },
          ],
          postings: 24, summary: '24 postings from 3 boards', elapsed_s: took(4800),
        }
      : null,
    discover: ran.includes('discover') ? { summary: '6 employers found', elapsed_s: took(6800) } : null,
    follow: ran.includes('follow') ? { summary: '4 followed, 1 unfollowable', elapsed_s: took(2000) } : null,
    collect: ran.includes('collect')
      ? { sites: [{ site: 'greenhouse', outcome: 'ok', count: 25 }], postings: 25, summary: '5 employers, 25 postings', elapsed_s: took(7000) }
      : null,
    match: ran.includes('match')
      ? { scored: 8, unscored_before: 8, failed: [], new_above_threshold: ids, top, summary: `8 scored, 2 new >= ${MIN_SCORE}`, elapsed_s: took(5200) }
      : null,
    new_above_threshold: ids,
    top,
    failures: [],
  }
  const runs = join(demoDir, 'jobs', 'runs')
  mkdirSync(runs, { recursive: true })
  writeFileSync(join(runs, recordName(startedAt)), JSON.stringify(record, null, 2))
  return record
}
