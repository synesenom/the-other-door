// The install test (#639): the app a user downloads, installed the user's way (setup.ts), goes through a first
// launch — the CV in, the review saved, the first run to its summary, a match prepared with the bundled
// Tectonic — then is quit and opened again. Its server is the bundled Python on the bundled door, with only the
// edges that would leave the computer answered from the test world (redirect.ts); Tectonic is the real, bundled
// one, so the first Prepare downloads its LaTeX packages. No real claude, no plan, no API key: the world's
// stand-in claude is first on PATH.
import { execFileSync, spawnSync } from 'node:child_process'
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, realpathSync, statSync, writeFileSync } from 'node:fs'
import { delimiter, join } from 'node:path'
import type { Page } from '@playwright/test'
import { expect, INSTALLED, launch, osStub, test } from '../journeys/fixtures'
import { LAUNCH, saveAndSearch, toReview } from '../journeys/helpers/onboarding'
import { pagesLoaded } from '../journeys/helpers/applications'
import { createTracker } from './close'
import { bundledPython, chromiumSigningChecks, documentedDataFolder, errorLines, kindOf, machOFiles } from './installer'
import type { Spawned } from './redirect'

test.use({ worldOptions: { empty: true, persona: 'mette' } })

const REPORT = join(__dirname, '..', 'install-report')

/** On Windows, the python, claude, door and Tectonic processes with their parents: what was still running (#18, #98). */
function processes(): string {
  if (process.platform !== 'win32') return ''
  try {
    return execFileSync('powershell', ['-NoProfile', '-Command',
      "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python|claude|door|tectonic' } | ForEach-Object { \"$($_.ProcessId) <$($_.ParentProcessId) $($_.Name): $($_.CommandLine.Substring(0, [Math]::Min(300, $_.CommandLine.Length)))\" }"],
      { encoding: 'utf8', timeout: 30_000 })
  } catch (p) { return `could not list: ${(p as Error).message}` }
}

/** Every app the test launched, tracked as it starts: each is closed on every path before the global teardown uninstalls (#111). */
const launched = createTracker()

const open = (world: Parameters<typeof launch>[0]): ReturnType<typeof launch> => launch(world, {}, launched.track)

// A failed run keeps, in the report CI uploads (#98): the data folder's logs (door.log: the server's stderr and exit
// status when it stopped), the world's server stacks, the stand-in claude's starts and the spawn, and the processes.
// Then every app still open is closed, its server with it: left running, they held the install folder on Windows
// and the uninstaller could not remove it (#111). What survives that (a server the quit did not wait for) is
// killed by the global teardown before it uninstalls.
test.afterEach(async ({ world }, info) => {
  if (info.status !== info.expectedStatus) keepReport(world)
  await launched.closeAll()
})

function keepReport(world: Parameters<typeof launch>[0]): void {
  try {
    cpSync(join(world.home, 'logs'), join(REPORT, 'logs'), { recursive: true })
  } catch {
    // no logs to keep
  }
  mkdirSync(join(REPORT, 'world'), { recursive: true })
  for (const f of ['server-stacks.txt', 'claude-starts.jsonl', 'spawned.json']) {
    if (existsSync(join(world.dir, f))) cpSync(join(world.dir, f), join(REPORT, 'world', f))
  }
  writeFileSync(join(REPORT, 'world', 'processes.txt'), processes())
}

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
  const first = await open(world)
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

  // doctor (the full check, which prints a page with the bundled Chromium, #176) finds the bundled Tectonic and no checkout
  const doctor = (await page.evaluate(() => window.door.call('doctor'))) as { data: { checks: { name: string; status: string; detail: string }[] } }
  expect(doctor.data?.checks, `doctor answered: ${JSON.stringify(doctor).slice(0, 2000)}`).toBeDefined()
  const checks = Object.fromEntries(doctor.data.checks.map((c) => [c.name, c]))
  expect(checks['latex']!.status).toBe('ok')
  expect(checks['latex']!.detail).toContain(join(resources, 'bin'))
  expect(checks['dev dependencies']).toBeUndefined()
  // the bundled Chromium headless shell that prints CVs (#165), found in the bundle
  expect(checks['chromium']?.status, JSON.stringify(checks['chromium'])).toBe('ok')
  expect(checks['chromium']!.detail).toContain(join(resources, 'bin', 'chromium'))
  // macOS: every Mach-O of the bundled Chromium passes codesign (#176), the hardened runtime too in a Developer ID build
  if (process.platform === 'darwin') {
    const signed = await app.evaluate(({ app }) => {
      const fs = process.mainModule!.require('node:fs') as typeof import('node:fs')
      const pkg = JSON.parse(fs.readFileSync(`${app.getAppPath()}/package.json`, 'utf8')) as { doorSigned?: boolean }
      return pkg.doorSigned === true
    })
    const files = machOFiles(join(resources, 'bin', 'chromium'))
    expect(files.length, 'no Mach-O file under bin/chromium').toBeGreaterThan(0)
    for (const check of chromiumSigningChecks(files, signed)) {
      const r = spawnSync(check.argv[0]!, check.argv.slice(1), { encoding: 'utf8' })
      expect(r.status, `${check.argv.join(' ')}: ${r.stderr}`).toBe(0)
      if (check.mustMatch) expect(r.stderr, check.argv.join(' ')).toMatch(check.mustMatch)
    }
  }
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
  try {
    await expect(summary(page)).toBeVisible({ timeout: 5 * 60_000 })
  } catch (e) {
    // name where the first run stood (#18): its progress record, the log's errors, the world's last calls, the screen
    const progress = existsSync(join(world.home, 'jobs', '.progress.json')) ? readFileSync(join(world.home, 'jobs', '.progress.json'), 'utf8') : 'none'
    const screen = await page.getByRole('main').innerText().catch(() => '')
    const starts = existsSync(join(world.dir, 'claude-starts.jsonl')) ? readFileSync(join(world.dir, 'claude-starts.jsonl'), 'utf8').trim().split('\n').slice(-6).join(' | ') : 'none'
    const stacksFile = join(world.dir, 'server-stacks.txt')
    const stacks = existsSync(stacksFile) ? (() => {
      // the last dump's thread running the find, whole (faulthandler starts each dump with the current thread)
      const blocks = readFileSync(stacksFile, 'utf8').split(/(?=Thread 0x|Current thread 0x)/)
      return blocks.filter((b) => b.includes('_find_core')).slice(-1).join('').slice(0, 12000)
    })() : 'none'
    const procs = processes()
    throw new Error(`${(e as Error).message}\nprogress: ${progress.slice(0, 3000)}\nlog errors: ${JSON.stringify(errors(world.home))}` +
      `\nlast calls: ${JSON.stringify(world.calls().slice(-15))}\nscreen: ${screen.slice(0, 1500)}\nclaude starts: ${starts}\nprocesses:\n${procs}\nserver stacks:\n${stacks}`)
  }
  await expect(page.getByRole('button', { name: /^Something keeps going wrong/ })).toHaveCount(0)
  expect(world.exists('profile/config.json')).toBe(true)
  expect(world.exists('profile/cv.md')).toBe(true)
  expect(filesIn(world.home, 'jobs/runs').filter((f) => f.endsWith('.json'))).toHaveLength(1)

  // Matches, the best one opened and prepared: the bundled Chromium prints both PDFs
  await summary(page).getByRole('button', { name: 'View matches' }).click()
  await expect(matchesHeading(page)).toBeVisible()
  const best = page.getByRole('main').getByRole('list').first().getByRole('listitem').first().getByRole('button').first()
  await best.click()
  await page.getByRole('button', { name: 'Prepare application', exact: true }).click()
  // a failed Prepare says so in the log at once: stop there with its message instead of waiting out the timeout
  const deadline = Date.now() + 10 * 60_000
  for (;;) {
    const logged = errors(world.home)
    if (logged.length) throw new Error(`Prepare failed: ${JSON.stringify(logged)}`)
    if (await readyHeading(page).isVisible()) break
    if (Date.now() > deadline) throw new Error('Prepare did not finish in time and logged no error')
    await page.waitForTimeout(2_000)
  }
  await pagesLoaded(page, 'Letter', 1)
  const output = filesIn(world.home, 'jobs/output')
  expect(output).toHaveLength(1)
  for (const f of ['cv.html', 'cover_letter.html', 'cv.pdf', 'cover_letter.pdf']) expect(world.exists(`jobs/output/${output[0]}/${f}`), f).toBe(true)
  expect(world.claudeCalls('tailor')).toHaveLength(1)
  // real PDFs, not the world's stand-ins: the header and at least one page object (#176)
  for (const f of ['cv.pdf', 'cover_letter.pdf']) {
    const bytes = readFileSync(join(world.home, 'jobs', 'output', output[0]!, f))
    expect(bytes.subarray(0, 4).toString(), `${f} is no PDF`).toBe('%PDF')
    expect(bytes.length, `${f} is empty`).toBeGreaterThan(1000)
    expect(bytes.toString('latin1'), `${f} has no page`).toMatch(/\/Type\s*\/Page\b/)
  }

  // the bundled Chromium prints a page with the installed interpreter, as the server would (#165; win64's shell on Windows on ARM too)
  const printed = join(world.scratch, 'chromium-print.pdf')
  execFileSync(spawned.command, ['-s', '-m', 'door.tailoring.html_pdf', '--out', printed], { env: { ...process.env, ...spawned.env }, encoding: 'utf8', timeout: 120_000 })
  expect(statSync(printed).size, 'chromium printed an empty PDF').toBeGreaterThan(1000)
  expect(readFileSync(printed).subarray(0, 4).toString()).toBe('%PDF')

  // nothing went wrong that the log saw, and the app wrote nothing inside itself
  expect(errors(world.home)).toEqual([])
  await app.close()
  if (!mounted) expect(snapshot(resources)).toEqual(before)

  // quit and open again: the profile, the match and the application are still there
  const again = await open(world)
  await expect(matchesHeading(again.page)).toBeVisible(LAUNCH)
  await expect(again.page.getByRole('main').getByRole('list').first().getByRole('listitem').first()).toBeVisible()
  await again.page.getByRole('navigation').getByRole('button', { name: 'Applications', exact: true }).click()
  await expect(again.page.getByRole('group', { name: 'Applications board' })).toBeVisible()
  await expect(again.page.getByRole('region', { name: 'Prepared', exact: true }).getByRole('button')).toHaveCount(1)
  expect(errors(world.home)).toEqual([])
  await again.app.close()
  if (!mounted) expect(snapshot(resources)).toEqual(before)
})
