// The simulated run of the demo, end to end in the built app: DOOR_DEMO_DIR (a temp folder) makes
// the unpackaged app a demo, and DOOR_DEMO_RUN_MS makes the 20 s script short. Nothing reaches the
// network or claude; the real jobs/ and profile/ and app/.demo are never touched.
import { existsSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { _electron as electron, expect, test } from '@playwright/test'
import { buildHome } from '../test/home-fixture'

const APP = resolve(__dirname, '..')
const fixture = buildHome()

test.skip(!fixture.hasPython, `no Python at ${fixture.python} (set DOOR_PYTHON)`)

let launches = 0
function launch(runMs: number) {
  // a demo folder of its own per test: the first one's postings must not reach the second
  const demo = join(fixture.scratch, `demo-${(launches += 1)}`)
  return {
    demo,
    app: electron.launch({
      args: ['.', ...(process.env.CI ? ['--no-sandbox'] : [])],
      cwd: APP,
      env: { ...(process.env as Record<string, string>), ...fixture.env, DOOR_DEMO_DIR: demo, DOOR_DEMO_RUN_MS: String(runMs) },
    }),
  }
}

const newPostings = (demo: string) => {
  const root = join(demo, 'jobs', 'postings')
  if (!existsSync(root)) return []
  return readdirSync(root, { recursive: true, encoding: 'utf8' }).filter((f) => f.includes('demo-new'))
}

test('Find new jobs plays the five steps, ends in a summary and View matches shows the new ones', async () => {
  const { app: starting, demo } = launch(6000)
  const app = await starting
  try {
    const page = await app.firstWindow()
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible({ timeout: 60_000 })
    await page.getByRole('complementary').getByRole('button', { name: 'Find new jobs' }).click()
    await expect(page.getByRole('heading', { name: 'Finding jobs', level: 1 })).toBeVisible()
    await expect(page.getByRole('list', { name: 'Steps' }).getByRole('listitem')).toHaveCount(5)
    await expect(page.getByRole('button', { name: 'Stop' })).toBeVisible()
    await expect(page.locator('.check-mark').first()).toBeVisible({ timeout: 15_000 })

    await expect(page.getByRole('heading', { level: 2, name: '2 new matches' })).toBeVisible({ timeout: 30_000 })
    expect(newPostings(demo)).toHaveLength(2)

    await page.getByRole('button', { name: 'View matches' }).click()
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible()
    await expect(page.getByRole('switch', { name: 'New only' })).toHaveAttribute('aria-checked', 'true')
    await expect(page.getByText('Finance Controller')).toBeVisible()
    await expect(page.getByText('Senior Business Controller')).toBeVisible()
  } finally {
    await app.close()
  }
})

test('Stop ends the run in the Stopped state and writes nothing', async () => {
  const { app: starting, demo } = launch(20_000)
  const app = await starting
  try {
    const page = await app.firstWindow()
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible({ timeout: 60_000 })
    await page.getByRole('complementary').getByRole('button', { name: 'Find new jobs' }).click()
    await expect(page.locator('.check-mark').first()).toBeVisible({ timeout: 15_000 })
    await page.getByRole('button', { name: 'Stop' }).click()
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible()
    await page.waitForTimeout(500)
    expect(newPostings(demo)).toHaveLength(0)
  } finally {
    await app.close()
  }
})
