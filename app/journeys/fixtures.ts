// The journeys' fixture: a test world (test/world/build.ts), the built app launched on it with the real
// door server, and the window, its clock set to the world's "now" so dates repeat.
// `test.use({ world: { persona: 'lea', empty: true } })` picks the world; `world.faults(...)` breaks things.
// DOOR_INSTALLED_APP=<executable> runs them against an installed app instead (the install test, #639): its
// bundled Python and door, the world's edges swapped in by e2e-install/redirect.ts; first launches only.
import { randomUUID } from 'node:crypto'
import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { _electron as electron, expect as baseExpect, test as base, type ElectronApplication, type Page } from '@playwright/test'
import { layEnv } from '../e2e-install/installer'
import { redirectServer } from '../e2e-install/redirect'
import { BUNDLED, buildWorld, NOW, type World, type WorldOptions } from '../test/world/build'
import { keepWorld } from './teardown'

const APP = resolve(__dirname, '..')
/** An installed app's executable: the journeys run against it, not the checkout's build. */
export const INSTALLED = process.env.DOOR_INSTALLED_APP || null

export interface Journey {
  world: World
  app: ElectronApplication
  page: Page
  /** Launch options of the world (set with test.use). */
  worldOptions: WorldOptions
  /** Stubbed main-process dialogs and shell: what the app asked of the OS. */
  os: OsStub
}

export interface OsStub {
  /** The next open dialog answers these paths (or a cancel with `null`). */
  nextOpen(paths: string[] | null): Promise<void>
  /** The next save dialog answers this path (or a cancel with `null`). */
  nextSave(path: string | null): Promise<void>
  /** URLs passed to shell.openExternal, and paths to shell.showItemInFolder. */
  opened(): Promise<{ external: string[]; shown: string[] }>
}

export async function launch(world: World, extraEnv: Record<string, string> = {}): Promise<{ app: ElectronApplication; page: Page }> {
  const spawned = join(world.dir, 'spawned.json')
  rmSync(spawned, { force: true })
  const toolCallsBefore = world.calls().filter((c) => c.kind === 'tool').length
  const flags = ['--lang=en-US', ...(process.env.CI ? ['--no-sandbox'] : [])]
  // An installed app checks for updates at start (#17): DOOR_UPDATES=off keeps it offline and on the version under test.
  const env = layEnv(process.env, { ...world.env, ...(INSTALLED ? { DOOR_UPDATES: 'off' } : {}), ...extraEnv })
  const app = INSTALLED
    ? // its own Chromium folder: an installed app's default is the user's real one, whatever HOME says
      await electron.launch({ executablePath: INSTALLED, args: [...flags, `--user-data-dir=${join(world.scratch, 'chromium')}`], env })
    : await electron.launch({ args: ['.', ...flags], cwd: APP, env })
  if (INSTALLED) await redirectServer(app, join(APP, 'test', 'world', 'boot.py'), world.dir)
  // The OS is never reached: links, folders and dialogs are recorded and answered from here.
  // (Playwright sometimes loses this first evaluate's promise to the main process's GC: it is idempotent, so it is sent again.)
  for (let attempt = 1; ; attempt++) {
    try {
  await app.evaluate(({ shell, dialog }) => {
    const g = globalThis as unknown as { __os: { external: string[]; shown: string[]; open: unknown[]; save: unknown[] } }
    g.__os = { external: [], shown: [], open: [], save: [] }
    shell.openExternal = (async (url: string) => {
      g.__os.external.push(url)
    }) as typeof shell.openExternal
    shell.showItemInFolder = ((path: string) => {
      g.__os.shown.push(path)
    }) as typeof shell.showItemInFolder
    shell.openPath = (async (path: string) => {
      g.__os.shown.push(path)
      return ''
    }) as typeof shell.openPath
    dialog.showOpenDialog = (async () => {
      const next = g.__os.open.shift() as string[] | null | undefined
      return next ? { canceled: false, filePaths: next } : { canceled: true, filePaths: [] }
    }) as unknown as typeof dialog.showOpenDialog
    dialog.showSaveDialog = (async () => {
      const next = g.__os.save.shift() as string | null | undefined
      return next ? { canceled: false, filePath: next } : { canceled: true, filePath: undefined }
    }) as unknown as typeof dialog.showSaveDialog
  })
      break
    } catch (e) {
      if (attempt >= 3 || !String(e).includes('garbage collected')) throw e
    }
  }
  const page = await app.firstWindow()
  // The window's clock starts at the world's "now", as the server's does (boot.py); time passes from there.
  await page.clock.install({ time: new Date(NOW) })
  // JOURNEYS_COVERAGE=1: the renderer's V8 block coverage from the first paint (the fixture writes it out).
  if (process.env.JOURNEYS_COVERAGE === '1') await page.coverage.startJSCoverage({ resetOnNavigation: false })
  await page.reload()
  if (INSTALLED) {
    await serverRedirected(world, toolCallsBefore)
    await page.reload()
  }
  return { app, page }
}

/**
 * The installed app's server runs boot.py now. The problem log's lines until here are the redirect's own (the
 * stopped server's "would not start"): they are cut, so the app does not count them as a problem that keeps
 * coming back (the window reloads after) and a test reads only what came after. (The new server appends: the file is cut in place.)
 */
async function serverRedirected(world: World, toolCallsBefore: number): Promise<void> {
  await baseExpect.poll(() => existsSync(join(world.dir, 'spawned.json')), { timeout: 60_000, message: 'the installed app started its server again through the redirect' }).toBe(true)
  await baseExpect.poll(() => world.calls().filter((c) => c.kind === 'tool').length > toolCallsBefore, { timeout: 60_000, message: 'the redirected server answers' }).toBe(true)
  const log = join(world.home, 'logs', 'door.log')
  if (existsSync(log)) writeFileSync(log, '')
}

export function osStub(app: ElectronApplication): OsStub {
  return {
    nextOpen: (paths) =>
      app.evaluate((_e, p) => {
        ;(globalThis as any).__os.open.push(p)
      }, paths),
    nextSave: (path) =>
      app.evaluate((_e, p) => {
        ;(globalThis as any).__os.save.push(p)
      }, path),
    opened: () => app.evaluate(() => ({ external: (globalThis as any).__os.external, shown: (globalThis as any).__os.shown })),
  }
}

export const test = base.extend<Journey>({
  worldOptions: [{}, { option: true }],
  world: async ({ worldOptions }, use, testInfo) => {
    const world = buildWorld(INSTALLED ? { ...worldOptions, python: BUNDLED, tectonic: false } : worldOptions)
    await use(world)
    // A failed test keeps its world to look at; the run's global teardown removes the others (journeys/teardown.ts).
    if (testInfo.status !== testInfo.expectedStatus) {
      testInfo.annotations.push({ type: 'world', description: world.scratch })
      keepWorld(world.scratch)
    }
  },
  app: async ({ world }, use) => {
    if (!world.hasPython) throw new Error(`no Python at ${world.python} (set DOOR_PYTHON)`)
    const { app } = await launch(world)
    await use(app)
    await app.close()
  },
  page: async ({ app }, use) => {
    const page = app.windows()[0]
    // JOURNEYS_COVERAGE=1: the renderer's V8 block coverage, one file per test (scripts/journeys-coverage.mts reads them).
    const covering = process.env.JOURNEYS_COVERAGE === '1'
    await use(page)
    if (covering) {
      const entries = (await page.coverage.stopJSCoverage()).filter((e) => /\/renderer\/assets\/index-[^/]+\.js$/.test(e.url))
      const dir = join(APP, 'journeys-coverage')
      mkdirSync(dir, { recursive: true })
      writeFileSync(join(dir, `${randomUUID()}.json`), JSON.stringify(entries.map((e) => ({ url: e.url, functions: e.functions, source: e.source }))))
    }
  },
  os: async ({ app }, use) => {
    await use(osStub(app))
  },
})

export const expect = baseExpect
