// Helpers of the Matches journeys (matches*.journey.ts): finding rows the way the user reads them,
// a run held by another process, and the notification clicks the main process forwards to the window.
import { spawn, type ChildProcess } from 'node:child_process'
import { join } from 'node:path'
import type { ElectronApplication, Locator, Page } from '@playwright/test'
import { expect } from '../fixtures'
import { repoRoot, type World } from '../../test/world/build'

export const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Mette's matches at min_score 0.65 that are not in her ledger, best first (what the list shows). */
export const METTE_ORDER = [
  'baltic-power-lead-ds',
  'vestvind-senior-ds-forecasting',
  'nordisk-elnet-prognose',
  'fjordpension-senior-ds',
  'gridwise-ml-engineer-remote',
  'region-midtkyst-patientflow',
  'klimadata-dataforsker',
  'torvehal-pricing-promotions',
  'egeskov-kommune-prognoser',
]
/** Scraped after the last review (4.5 days ago): the new ones. */
export const METTE_NEW = ['baltic-power-lead-ds', 'vestvind-senior-ds-forecasting', 'torvehal-pricing-promotions']

/** The rows of the Matches list. */
export function matchRows(page: Page): Locator {
  return page.getByRole('main').getByRole('list').first().getByRole('listitem')
}

/** The row button of an ad, by its title (the accessible name starts with the dot's label or the title). */
export function row(page: Page, world: World, key: string): Locator {
  return page.getByRole('main').getByRole('listitem').getByRole('button', { name: new RegExp(escapeRe(world.ads[key].title)) })
}

/** The Matches list, loaded. */
export async function matchesLoaded(page: Page, count = METTE_ORDER.length): Promise<void> {
  await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible({ timeout: 60_000 })
  await expect(matchRows(page)).toHaveCount(count)
}

/** The posting's heading (h2) of an ad. */
export function postingHeading(page: Page, world: World, key: string): Locator {
  return page.getByRole('heading', { name: world.ads[key].title, level: 2, exact: true })
}

/** Opens an ad from the list and waits for its posting to load. */
export async function openRow(page: Page, world: World, key: string): Promise<void> {
  await row(page, world, key).click()
  await expect(postingHeading(page, world, key)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Status', exact: true })).toBeVisible()
}

/** What the user reads as the title of a posting in dialogs and notices: the English one when there is one. */
export const shownTitle = (world: World, key: string) => world.ads[key].titleEn || world.ads[key].title

/** A notification click: the main process sends `door:open` with this target. */
export async function notificationOpens(app: ElectronApplication, target: unknown): Promise<void> {
  await app.evaluate(({ BrowserWindow }, t) => BrowserWindow.getAllWindows()[0].webContents.send('door:open', t), target)
}

/** A window narrower than 900 px. */
export async function narrowWindow(app: ElectronApplication, page: Page): Promise<void> {
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(760, 800))
  await expect.poll(() => page.evaluate(() => window.innerWidth)).toBeLessThan(900)
}

/** The seen ids in jobs/last_review.json. */
export function seenOnDisk(world: World): string[] {
  try {
    return world.readJson<{ seen?: string[] }>('jobs/last_review.json').seen ?? []
  } catch {
    return []
  }
}

export interface HeldRun {
  release(): Promise<void>
}

/**
 * A run of another process (a `./door find` in a terminal): it holds the real ledger lock and reports
 * `message`, so the server refuses ledger writes and the app sees a run started elsewhere.
 */
export async function holdRun(world: World, message = 'search: reading jobindex'): Promise<HeldRun> {
  const code = [
    'import sys',
    'from pathlib import Path',
    'from door.core import lock, progress',
    'lock.pre_acquire_hook = lambda *a, **k: None',
    'lock.post_release_hook = lambda *a, **k: None',
    'with lock.ledger_lock(Path(sys.argv[1]), "run"):',
    '    progress.report(sys.argv[2], stage="step", site="search")',
    '    print("held", flush=True)',
    '    sys.stdin.read()',
  ].join('\n')
  const child: ChildProcess = spawn(world.python, ['-c', code, join(world.home, 'jobs'), message], {
    env: { ...process.env, PYTHONPATH: join(repoRoot, 'src'), DOOR_HOME: world.home, HOME: world.env.HOME },
    stdio: ['pipe', 'pipe', 'pipe'],
  })
  let err = ''
  child.stderr?.on('data', (d) => (err += String(d)))
  await new Promise<void>((resolve, reject) => {
    child.stdout?.on('data', (d) => String(d).includes('held') && resolve())
    child.on('exit', (c) => reject(new Error(`the held run exited (${c}): ${err}`)))
  })
  return {
    release: () =>
      new Promise<void>((resolve) => {
        if (child.exitCode !== null) return resolve()
        child.on('exit', () => resolve())
        child.stdin?.end()
      }),
  }
}
