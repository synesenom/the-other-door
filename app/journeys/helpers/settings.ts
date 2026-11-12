// The Settings journeys' own helpers: reaching Settings, seeding the world before the
// app starts (`test.use({ seed })`), door's own Python on the world's home (an export, sync's fingerprint),
// and a stand-in `curl` so Fix and Install run their real install commands without the internet.
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync, chmodSync } from 'node:fs'
import { join } from 'node:path'
import type { Locator, Page } from '@playwright/test'
import { repoRoot, type World } from '../../test/world/build'
import { expect, test as base } from '../fixtures'

/** A first launch may take a while: the server starts, doctor answers. */
export const LAUNCH = { timeout: 60_000 }

/** What to change in the world before the app starts: `test.use({ seed: before((world) => ...) })`. */
export interface Seed {
  run: (world: World) => void
}
export const before = (run: (world: World) => void): Seed => ({ run })

/** The journeys' test, plus the `seed` option (a function itself would be taken for a fixture). */
export const test = base.extend<{ seed: Seed | undefined }>({
  seed: [undefined, { option: true }],
  world: async ({ world, seed }, use) => {
    seed?.run(world)
    await use(world)
  },
})

export const sidebar = (page: Page): Locator => page.getByRole('complementary')
export const needsYou = (page: Page): Locator => page.getByRole('group', { name: 'Needs you' })
export const claudeRow = (page: Page): Locator => page.getByRole('listitem', { name: 'Claude', exact: true })
export const driveRow = (page: Page): Locator => page.getByRole('listitem', { name: 'Google Drive', exact: true })
export const phoneRow = (page: Page): Locator => page.getByRole('listitem', { name: 'Your phone', exact: true })
export const region = (page: Page, name: string): Locator => page.getByRole('region', { name, exact: true })
export const dialog = (page: Page, name: string): Locator => page.getByRole('dialog', { name, exact: true })
export const button = (scope: Page | Locator, name: string): Locator => scope.getByRole('button', { name, exact: true })

/** The app open on Matches (the first screen), then Settings from the sidebar, with doctor's answer on screen. */
export async function openSettings(page: Page): Promise<void> {
  await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible(LAUNCH)
  await goToSettings(page)
}

export async function goToSettings(page: Page): Promise<void> {
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible()
  await expect(claudeRow(page).getByText('Checking Claude…')).toHaveCount(0, LAUNCH)
}

export async function goToMatches(page: Page): Promise<void> {
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Matches', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible()
}

/** Scrolls the page back to its top (under an open dialog too): the data folder's path goes out of view. */
export const scrollToTop = (page: Page) =>
  page.evaluate(() => {
    for (const box of [document.querySelector('main'), document.scrollingElement, document.body]) box?.scrollTo(0, 0)
  })


/** door's own Python on the world's home, for what a test must build that the app has no button for. */
export function py(world: World, code: string, ...args: string[]): string {
  return execFileSync(world.python, ['-c', code, ...args], {
    env: { ...world.env, PATH: process.env.PATH ?? '', PYTHONPATH: join(repoRoot, 'src') },
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  }).trim()
}

/** An export of the world's home as it is now (door's own `data export`), written to `target`. */
export function exportHome(world: World, target: string): string {
  py(world, 'import sys; from door.commands import archive; archive._export_core(sys.argv[1])', target)
  return target
}

/** Every file in a .zip, as text by name (door's own Python reads it: the app has no unzip). */
export function zipContents(world: World, path: string): Record<string, string> {
  return JSON.parse(py(world, 'import json, sys, zipfile; z = zipfile.ZipFile(sys.argv[1]); print(json.dumps({n: z.read(n).decode("utf-8") for n in z.namelist()}))', path))
}

/** The fake Drive: its one archive, and the computer's sync state. */
export const driveArchive = (world: World) => join(world.dir, 'drive', 'door-data.tar.gz')
export const driveState = (world: World) => join(world.dir, 'config', 'drive.json')
export const readDriveState = (world: World): Record<string, unknown> | null =>
  existsSync(driveState(world)) ? JSON.parse(readFileSync(driveState(world), 'utf8')) : null

/** The file names inside a .tar.gz. */
export function tarList(path: string): string[] {
  return execFileSync('tar', ['-tzf', path], { encoding: 'utf8' }).split('\n').filter(Boolean)
}

/** Writes keys into the computer's Drive state (as door's own sync would have left them). */
export function patchDriveState(world: World, patch: Record<string, unknown>): void {
  mkdirSync(join(world.dir, 'config'), { recursive: true })
  writeFileSync(driveState(world), JSON.stringify({ ...(readDriveState(world) ?? {}), ...patch }))
}

/** sync's fingerprint of the home as it is now: "this computer has not changed since". */
export function fingerprint(world: World): string {
  return py(world, 'import sys; from pathlib import Path; from door.core import sync; h = Path(sys.argv[1]); print(sync.fingerprint(h / "profile", h / "jobs"))', world.home)
}

/** world.json, changed in place (the server reads it again on every call). */
export function editWorld(world: World, change: (w: any) => void): void {
  const path = join(world.dir, 'world.json')
  const w = JSON.parse(readFileSync(path, 'utf8'))
  change(w)
  writeFileSync(path, JSON.stringify(w, null, 2))
}

/**
 * A stand-in `curl`, first on the server's PATH, so `setup`'s real install commands run offline: for the
 * claude installer it prints a script that puts the world's stand-in into ~/.local/bin (the isolated user
 * home). `fail` makes it exit 7 as curl does when it cannot connect. It never reaches the network.
 */
export function standInCurl(world: World, how: 'works' | 'fail' = 'works'): void {
  const bin = join(world.scratch, 'bin')
  const claude = `exec "${world.python}" "${join(repoRoot, 'app', 'test', 'world', 'claude.py')}" "${world.dir}" "$@"`
  const lines =
    how === 'fail'
      ? ['#!/bin/sh', `echo "$@" >> "${join(world.dir, 'curl-args')}"`, 'echo "curl: (7) Failed to connect to the internet: the test world has none" >&2', 'exit 7']
      : [
          '#!/bin/sh',
          `echo "$@" >> "${join(world.dir, 'curl-args')}"`,
          'case "$*" in',
          `  *claude.ai/install.sh*) printf '%s\\n' 'mkdir -p "$HOME/.local/bin"' 'cat > "$HOME/.local/bin/claude" <<"EOF"' '#!/bin/sh' '${claude}' 'EOF' 'chmod +x "$HOME/.local/bin/claude"' ;;`,
          '  *) echo "curl: (6) the test world has no $*" >&2; exit 6 ;;',
          'esac',
        ]
  writeFileSync(join(bin, 'curl'), lines.join('\n') + '\n')
  chmodSync(join(bin, 'curl'), 0o755)
}

/** "The phone scanned the code": the pretend server pairs it at its next status. */
export const phoneScans = (world: World) => writeFileSync(join(world.dir, 'phone-scanned'), '')
