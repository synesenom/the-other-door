// A job whose application is already prepared (a fixture output folder, no model, no
// LaTeX): Applications -> See the application -> the page images load through the
// door-file scheme -> Undo has nothing to undo. Temp home only.
import { resolve } from 'node:path'
import { _electron as electron, expect, test } from '@playwright/test'
import { buildHome } from '../test/home-fixture'

const APP = resolve(__dirname, '..')
const own = buildHome({ prepared: 'jobindex.123' })

test.skip(!own.hasPython, `no Python at ${own.python} (set DOOR_PYTHON)`)

test('opens a prepared application, shows its pages and has nothing to undo', async () => {
  const app = await electron.launch({
    args: ['.', ...(process.env.CI ? ['--no-sandbox'] : [])],
    cwd: APP,
    env: { ...(process.env as Record<string, string>), ...own.env },
  })
  try {
    const page = await app.firstWindow()
    await expect(page.getByRole('listitem')).toHaveCount(1, { timeout: 60_000 })
    await page.getByRole('navigation').getByRole('button', { name: 'Applications' }).click()
    await page.getByRole('button', { name: /Dataanalytiker|Data Analyst/ }).click()
    await expect(page.getByRole('heading', { name: 'Dataanalytiker', level: 2 })).toBeVisible()
    await page.getByRole('button', { name: 'See the application' }).click()

    await expect(page.getByRole('heading', { name: 'Ready to send' })).toBeVisible()
    // One document at a time: the letter first, then the CV behind the switch; every page loads.
    const images = page.locator('img.paper')
    const loaded = async (count: number) => {
      await expect(images).toHaveCount(count)
      for (let i = 0; i < count; i++) {
        const width = await images.nth(i).evaluate(async (el) => {
          const img = el as HTMLImageElement
          await img.decode()
          return img.naturalWidth
        })
        expect(width).toBeGreaterThan(0)
      }
    }
    await loaded(1)
    await expect(page.getByRole('button', { name: /^Letter · 3\d\d words$/ })).toBeVisible()
    await page.getByRole('button', { name: 'CV · 2 pages' }).click()
    await loaded(2)
    await expect(page.getByRole('button', { name: 'Save CV' })).toBeVisible()

    await page.getByRole('button', { name: 'Undo last change' }).click()
    await expect(page.getByText('Nothing to undo.')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole('alert')).toHaveCount(0)

    await page.getByRole('button', { name: '← Posting' }).click()
    await expect(page.getByRole('heading', { name: 'Dataanalytiker', level: 2 })).toBeVisible()
  } finally {
    await app.close()
  }
})
