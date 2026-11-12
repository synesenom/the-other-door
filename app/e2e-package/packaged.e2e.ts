// The packaged app on its own (#223): it starts its bundled Python on its bundled door, keeps the data where it
// is told (a temp DOOR_HOME here) and writes nothing inside itself. The stand-in claude is first on PATH and
// HOME is a temp folder, so the real claude and your data are never reached.
import { existsSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { _electron as electron, expect, test } from '@playwright/test'
import { buildHome } from '../test/home-fixture'

const APP = resolve(__dirname, '..')

/** The packaged executable: DOOR_PACKAGED_APP, else what `npm run package:dir` built for this system. */
function executable(): string | null {
  if (process.env.DOOR_PACKAGED_APP) return process.env.DOOR_PACKAGED_APP
  const dist = join(APP, 'dist')
  if (!existsSync(dist)) return null
  for (const dir of readdirSync(dist)) {
    const candidates =
      process.platform === 'darwin'
        ? [join(dist, dir, 'The other door.app', 'Contents', 'MacOS', 'The other door')]
        : process.platform === 'win32'
          ? [join(dist, dir, 'the-other-door.exe')]
          : [join(dist, dir, 'the-other-door')]
    const found = candidates.find((c) => existsSync(c))
    if (found) return found
  }
  return null
}

/** Every file of the app's resources with its modification time: a change means it wrote inside itself. */
function snapshot(root: string): string[] {
  return (readdirSync(root, { recursive: true, encoding: 'utf8' }) as string[]).sort().map((f) => `${f}@${statSync(join(root, f)).mtimeMs}`)
}

const exe = executable()
// In CI a missing app is a failure (a skipped smoke test would pass a build nobody tried); locally, a skip.
if (process.env.CI && !exe) throw new Error('no packaged app in dist/ and no DOOR_PACKAGED_APP: the build did not produce one')
test.skip(!exe, 'no packaged app: run `npm run package:dir` first, or set DOOR_PACKAGED_APP')

test('the packaged app serves Matches from its bundle and writes nothing inside itself', async () => {
  const resources = process.platform === 'darwin' ? resolve(dirname(exe!), '..', 'Resources') : join(dirname(exe!), 'resources')
  expect(existsSync(join(resources, 'python')), 'the bundled Python').toBe(true)
  const before = snapshot(resources)
  const fixture = buildHome()
  const app = await electron.launch({
    executablePath: exe!,
    args: process.env.CI ? ['--no-sandbox'] : [],
    env: { ...(process.env as Record<string, string>), ...fixture.env, DOOR_PYTHON: '' },
  })
  try {
    const page = await app.firstWindow()
    await expect(page.getByRole('listitem').filter({ hasText: 'Dataanalytiker' })).toBeVisible({ timeout: 120_000 })
    const info = await page.evaluate(() => window.door.info())
    expect(info.home).toBe(fixture.home)
    const doctor = (await page.evaluate(() => window.door.call('doctor'))) as { ok: boolean; data: { checks: { name: string; status: string; detail: string }[] } }
    const checks = Object.fromEntries(doctor.data.checks.map((c) => [c.name, c]))
    expect(checks['latex']!.status).toBe('ok')
    expect(checks['latex']!.detail).toContain(join(resources, 'bin'))
    expect(checks['dev dependencies']).toBeUndefined()
  } finally {
    await app.close()
  }
  expect(snapshot(resources)).toEqual(before)
})
