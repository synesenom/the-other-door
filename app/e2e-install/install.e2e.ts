// The install test (#639): the app a user downloads, installed the user's way (setup.ts), goes through a first
// launch — the CV in, the review saved, the first run to its summary, a match prepared with the bundled
// Tectonic — then is quit and opened again. Its server is the bundled Python on the bundled door, with only the
// edges that would leave the computer answered from the test world (redirect.ts); Tectonic is the real, bundled
// one, so the first Prepare downloads its LaTeX packages. No real claude, no plan, no API key: the world's
// stand-in claude is first on PATH.
import { existsSync, readdirSync, readFileSync, realpathSync, statSync } from 'node:fs'
import { delimiter, join } from 'node:path'
import type { Page } from '@playwright/test'
import { expect, INSTALLED, launch, osStub, test } from '../journeys/fixtures'
import { LAUNCH, saveAndSearch, toReview } from '../journeys/helpers/onboarding'
import { pagesLoaded } from '../journeys/helpers/applications'
import { bundledPython, documentedDataFolder, errorLines, kindOf } from './installer'
import type { Spawned } from './redirect'

test.use({ worldOptions: { empty: true, persona: 'mette' } })

const summary = (page: Page) => page.getByRole('region', { name: 'Run summary' })
const readyHeading = (page: Page) => page.getByRole('heading', { name: 'Ready to send', level: 1 })
const matchesHeading = (page: Page) => page.getByRole('heading', { name: 'Matches', level: 1 })

/** Every file of the app's resources with its modification time: a change means it wrote inside itself. */
function snapshot(root: string): string[] {
  return (readdirSync(root, { recursive: true, encoding: 'utf8' }) as string[]).sort().map((f) => `${f}@${statSync(join(root, f)).mtimeMs}`)
}

/** The ERROR lines of the problem log since the server was redirected (journeys/fixtures.ts cuts the redirect's own). */
const errors = (home: string): string[] => errorLines(existsSync(join(home, 'logs', 'door.log')) ? readFileSync(join(home, 'logs', 'door.log'), 'utf8') : '')

/** The files of a folder of the data folder, or none. */
const filesIn = (home: string, rel: string): string[] => (existsSync(join(home, rel)) ? readdirSync(join(home, rel)) : [])

test('the installed app: set-up, the first run and Prepare on what the installer brought; reopened, the data is still there', async ({ world }) => {
  const first = await launch(world)
  const { app, page } = first
  const os = osStub(app)
  const resources = await app.evaluate(() => process.resourcesPath)
  // an AppImage's resources are a read-only mount that goes away when the app quits: nothing to compare
  const mounted = kindOf(INSTALLED ?? '') === 'appimage'
  const before = mounted ? [] : snapshot(resources)

  // the server: the bundled Python on the bundled door, the bundled Tectonic first on its PATH
  const spawned = JSON.parse(readFileSync(join(world.dir, 'spawned.json'), 'utf8')) as Spawned
  expect(spawned.command).toBe(bundledPython(resources, process.platform))
  expect(spawned.args).toEqual(['-s', '-m', 'door.mcp_server'])
  expect(spawned.env.PYTHONPATH).toBe(join(resources, 'door', 'src'))
  expect(spawned.env.DOOR_HOME).toBe(world.home)
  expect(spawned.env.PATH!.split(delimiter)[0]).toBe(join(resources, 'bin'))

  // doctor finds the bundled Tectonic and no checkout
  const doctor = (await page.evaluate(() => window.door.call('doctor'))) as { data: { checks: { name: string; status: string; detail: string }[] } }
  expect(doctor.data?.checks, `doctor answered: ${JSON.stringify(doctor).slice(0, 2000)}`).toBeDefined()
  const checks = Object.fromEntries(doctor.data.checks.map((c) => [c.name, c]))
  expect(checks['latex']!.status).toBe('ok')
  expect(checks['latex']!.detail).toContain(join(resources, 'bin'))
  expect(checks['dev dependencies']).toBeUndefined()
  // the world's stand-in claude, found and signed in: else the wizard opens on Connect
  const claude = JSON.stringify([checks['claude CLI'], checks['claude login']])
  expect(checks['claude CLI']?.status, claude).toBe('ok')
  expect(checks['claude login']?.status, claude).toBe('ok')

  // with no DOOR_HOME the data would be where the manual says
  // (the test runs it on its own Chromium folder and DOOR_HOME: the default is the app's name in the system's app data)
  const [userData, name, home, appData] = await app.evaluate(({ app }) => [app.getPath('userData'), app.getName(), app.getPath('home'), app.getPath('appData')])
  expect(realpathSync(userData)).toBe(realpathSync(join(world.scratch, 'chromium')))
  expect(join(appData, name)).toBe(documentedDataFolder(process.platform, home, appData))

  // set-up: the CV in, read, reviewed and saved; the first run starts (a first screen other than Sources is named)
  await expect(page.getByRole('heading', { level: 1 }).first()).toHaveText('Tell me about yourself', LAUNCH)
  try {
    await toReview(page, world, os)
  } catch (e) {
    // name what Windows (#18) stopped on: the screen's error, the log's errors, the stand-in claude's calls with their times
    const alerts = await page.getByRole('alert').allInnerTexts().catch(() => [])
    const calls = world.calls().filter((c) => c.kind === 'claude').slice(-10)
    throw new Error(`${(e as Error).message}\nalerts: ${JSON.stringify(alerts)}\nlog errors: ${JSON.stringify(errors(world.home))}\nclaude calls: ${JSON.stringify(calls)}`)
  }
  await saveAndSearch(page).click()
  await expect(page.getByRole('heading', { name: 'Finding jobs', level: 1 })).toBeVisible(LAUNCH)
  await expect(summary(page)).toBeVisible({ timeout: 5 * 60_000 })
  await expect(page.getByRole('button', { name: /^Something keeps going wrong/ })).toHaveCount(0)
  expect(world.exists('profile/config.json')).toBe(true)
  expect(world.exists('profile/cv.md')).toBe(true)
  expect(filesIn(world.home, 'jobs/runs').filter((f) => f.endsWith('.json'))).toHaveLength(1)

  // Matches, the best one opened and prepared: the real Tectonic compiles both PDFs
  await summary(page).getByRole('button', { name: 'View matches' }).click()
  await expect(matchesHeading(page)).toBeVisible()
  const best = page.getByRole('main').getByRole('list').first().getByRole('listitem').first().getByRole('button').first()
  await best.click()
  await page.getByRole('button', { name: 'Prepare application', exact: true }).click()
  // a failed Prepare says so in the log at once: stop there with its message instead of waiting out the timeout
  await expect
    .poll(async () => (errors(world.home).length ? errors(world.home) : (await readyHeading(page).isVisible()) ? 'ready' : 'preparing'), {
      timeout: 10 * 60_000,
      intervals: [2_000],
    })
    .toBe('ready')
  await pagesLoaded(page, 'Letter', 1)
  const output = filesIn(world.home, 'jobs/output')
  expect(output).toHaveLength(1)
  for (const f of ['cv.tex', 'cover_letter.tex', 'cv.pdf', 'cover_letter.pdf']) expect(world.exists(`jobs/output/${output[0]}/${f}`), f).toBe(true)
  expect(world.claudeCalls('tailor')).toHaveLength(1)

  // nothing went wrong that the log saw, and the app wrote nothing inside itself
  expect(errors(world.home)).toEqual([])
  await app.close()
  if (!mounted) expect(snapshot(resources)).toEqual(before)

  // quit and open again: the profile, the match and the application are still there
  const again = await launch(world)
  try {
    await expect(matchesHeading(again.page)).toBeVisible(LAUNCH)
    await expect(again.page.getByRole('main').getByRole('list').first().getByRole('listitem').first()).toBeVisible()
    await again.page.getByRole('navigation').getByRole('button', { name: 'Applications', exact: true }).click()
    await expect(again.page.getByRole('group', { name: 'Applications board' })).toBeVisible()
    await expect(again.page.getByRole('region', { name: 'Prepared', exact: true }).getByRole('button')).toHaveCount(1)
    expect(errors(world.home)).toEqual([])
  } finally {
    await again.app.close()
  }
  if (!mounted) expect(snapshot(resources)).toEqual(before)
})
