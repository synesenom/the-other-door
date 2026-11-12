// The phone app end to end (#303): the web build served by a real `door serve` on the demo's made-up
// data, in a phone-sized window. Pairing through the QR code's link, Matches, a posting, Applications, a
// prepared application's pages loaded through /files, and what belongs to the door machine.
import { resolve } from 'node:path'
import { _electron as electron, expect, test } from '@playwright/test'
import { phoneProfile, serveDemo, type Served } from './serve-fixture'

const APP = resolve(__dirname, '..')
let served: Served

test.beforeAll(async () => {
  served = await serveDemo()
})
test.afterAll(() => served?.stop())

test('pair by the link, then Matches, a posting, Applications and a prepared application', async () => {
  test.skip(!served.fixture.hasPython, `no Python at ${served.fixture.python}`)
  const app = await electron.launch({
    args: [resolve(__dirname, 'browser.cjs'), ...(process.env.CI ? ['--no-sandbox'] : [])],
    cwd: APP,
    env: { ...(process.env as Record<string, string>), DOOR_WEB_PROFILE: phoneProfile(served.fixture), DOOR_WEB_URL: `${served.url}/#pair=${served.code}` },
  })
  try {
    const page = await app.firstWindow()
    // the code in the link pairs; the app opens on Matches with the tab bar at the bottom
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible({ timeout: 30_000 })
    expect(page.url()).not.toContain('#pair=')
    const tabs = page.getByRole('navigation')
    await expect(tabs.getByRole('button', { name: 'Applications' })).toBeVisible()

    // a posting, pushed, and back
    await page.getByText('Senior Financial Controller').first().click()
    await expect(page.getByRole('heading', { name: 'Senior Financial Controller', level: 2 })).toBeVisible()
    await page.getByRole('button', { name: /Matches/ }).first().click()

    // Applications, the prepared one, its pages through /files
    await tabs.getByRole('button', { name: 'Applications' }).click()
    await page.getByRole('button', { name: /Finance Manager/ }).first().click()
    await page.getByRole('button', { name: 'See the application' }).click()
    const paper = page.locator('img.paper').first()
    await expect(paper).toBeVisible({ timeout: 20_000 })
    const width = await paper.evaluate(async (el) => {
      const img = el as HTMLImageElement
      await img.decode()
      return img.naturalWidth
    })
    expect(width).toBeGreaterThan(0)

    // a reload keeps the pairing (the token is in IndexedDB)
    await page.goto(served.url)
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible({ timeout: 30_000 })
  } finally {
    await app.close()
  }
})

test('a wrong code is refused and the pair screen stays', async () => {
  const app = await electron.launch({
    args: [resolve(__dirname, 'browser.cjs'), ...(process.env.CI ? ['--no-sandbox'] : [])],
    cwd: APP,
    env: { ...(process.env as Record<string, string>), DOOR_WEB_PROFILE: phoneProfile(served.fixture), DOOR_WEB_URL: `${served.url}/#pair=AAAA-AAAA` },
  })
  try {
    const page = await app.firstWindow()
    await expect(page.getByRole('alert')).toContainText('wrong or has expired', { timeout: 30_000 })
    await expect(page.getByRole('heading', { name: 'Pair this phone' })).toBeVisible()
  } finally {
    await app.close()
  }
})
