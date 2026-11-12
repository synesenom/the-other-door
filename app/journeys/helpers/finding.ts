// Helpers of the Find new jobs journeys (finding.journey.ts): the sidebar's button, the world's boards,
// a run started elsewhere (the real ledger lock held by another process).
import { spawn, type ChildProcess } from 'node:child_process'
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import type { Locator, Page } from '@playwright/test'
import { repoRoot, type World } from '../../test/world/build'

/** The sidebar's run button, whatever it says ("Find new jobs" or "Finding jobs…"). */
export function runButton(page: Page): Locator {
  return page.getByRole('complementary').getByRole('button', { name: /^(Find new jobs|Finding jobs…)$/ })
}

export const steps = (page: Page) => page.getByRole('list', { name: 'Steps' })

/** One row of the Steps list, by its heading ("Search", "Match"…). */
export function stepRow(page: Page, title: string): Locator {
  return steps(page).getByRole('listitem').filter({ has: page.getByRole('heading', { level: 2, name: title, exact: true }) })
}

/** A step is done when its mark is the check (the number is gone). */
export function stepDone(page: Page, title: string): Locator {
  return stepRow(page, title).locator('.check-mark')
}

/** Rewrites one board of world.json (`fail` makes it record an error and return nothing). */
export function setBoard(world: World, site: string, board: { fail?: string; postings?: unknown[] }): void {
  const path = join(world.dir, 'world.json')
  const w = JSON.parse(readFileSync(path, 'utf8'))
  w.boards[site] = { ...w.boards[site], ...board }
  if (board.fail === undefined) delete w.boards[site].fail
  writeFileSync(path, JSON.stringify(w, null, 2))
}

/** Removes keys from profile/config.json (a discovery source "never chosen" is a key that is not set). */
export function unsetConfig(world: World, keys: string[]): void {
  const path = join(world.home, 'profile', 'config.json')
  const config = JSON.parse(readFileSync(path, 'utf8'))
  for (const k of keys) delete config[k]
  writeFileSync(path, JSON.stringify(config, null, 2))
}

/** The run records on disk (not latest.log), oldest first. */
export function runRecords(world: World): string[] {
  const dir = join(world.home, 'jobs', 'runs')
  if (!existsSync(dir)) return []
  return readdirSync(dir)
    .filter((f) => f.endsWith('.json'))
    .sort()
}

/** The posting of `id` on disk (any day folder), or null. */
export function postingOf(world: World, id: string): Record<string, any> | null {
  const dir = join(world.home, 'jobs', 'postings')
  if (!existsSync(dir)) return null
  const hit = (readdirSync(dir, { recursive: true, encoding: 'utf8' }) as string[]).find((f) => f.endsWith(`/${id}.json`))
  return hit ? JSON.parse(readFileSync(join(dir, hit), 'utf8')) : null
}

/** The steps of a run half way: search done, discover skipped, follow running, collect and match waiting. */
export function halfWaySteps(startedAt: string) {
  return [
    { name: 'search', status: 'done', detail: '3 new postings from 3 boards', started_at: startedAt, finished_at: startedAt },
    { name: 'discover', status: 'skipped', detail: 'linkedin_discovery is off' },
    { name: 'follow', status: 'running', detail: '', started_at: startedAt, done: 1, total: 4 },
    { name: 'collect', status: 'waiting', detail: '' },
    { name: 'match', status: 'waiting', detail: '' },
  ]
}

export interface HeldLock {
  /** The holder's pid. */
  pid: number
  /** Releases the lock (the holder exits) and waits until it has. */
  release(): Promise<void>
}

/** Another process of The other door holding the real ledger lock (`ledger_lock(jobs, purpose)`), as a run
 *  from a terminal would; with `steps`, it also writes them to `.progress.json` for the run board. */
export async function holdLedgerLock(world: World, purpose: string, opts: { steps?: unknown[]; startedAt?: string } = {}): Promise<HeldLock> {
  const code = [
    'import json, sys',
    'from pathlib import Path',
    'from door.core import lock',
    // no Drive sync around it: the holder only holds
    'lock.pre_acquire_hook = lambda *a, **k: None',
    'lock.post_release_hook = lambda *a, **k: None',
    'jobs = Path(sys.argv[1])',
    'with lock.ledger_lock(jobs, sys.argv[2]):',
    // a start the screen can show the same way every time (the holder's own clock is the real one)
    '    if sys.argv[4]:',
    '        info = json.loads((jobs / ".lock.json").read_text())',
    '        (jobs / ".lock.json").write_text(json.dumps({**info, "started_at": sys.argv[4]}))',
    '    if sys.argv[3] != "null":',
    '        (jobs / ".progress.json").write_text(json.dumps({"message": "", "steps": json.loads(sys.argv[3])}))',
    '    print("held", flush=True)',
    '    sys.stdin.read()',
  ].join('\n')
  const child: ChildProcess = spawn(world.python, ['-c', code, join(world.home, 'jobs'), purpose, opts.steps ? JSON.stringify(opts.steps) : 'null', opts.startedAt ?? ''], {
    env: { ...process.env, ...world.env, PYTHONPATH: join(repoRoot, 'src') },
    stdio: ['pipe', 'pipe', 'pipe'],
  })
  let err = ''
  child.stderr?.on('data', (d) => (err += String(d)))
  await new Promise<void>((resolve, reject) => {
    child.stdout?.on('data', (d) => String(d).includes('held') && resolve())
    child.on('exit', (code) => reject(new Error(`the lock holder exited (${code}): ${err}`)))
  })
  return {
    pid: child.pid!,
    release: () =>
      new Promise<void>((resolve) => {
        if (child.exitCode !== null) return resolve()
        child.on('exit', () => resolve())
        child.stdin?.end()
      }),
  }
}
