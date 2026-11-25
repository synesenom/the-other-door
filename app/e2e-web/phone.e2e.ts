// The phone app end to end (#303): the web build served by a real `door serve` on the demo's made-up
// data, in a phone-sized window. Pairing through the QR code's link, Matches, a posting, Applications, a
// prepared application's pages loaded through /files, and what belongs to the door machine.
import { resolve } from 'node:path'
import { _electron as electron, devices, expect, test, webkit } from '@playwright/test'
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
    await expect(page.getByRole('heading', { name: 'Ready to send' })).toBeVisible()
    await expect(page.getByLabel('Anything to change?')).toHaveCount(0)
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

/** A 390 px phone that pairs with a fresh code. */
async function openPaired() {
  return electron.launch({
    args: [resolve(__dirname, 'browser.cjs'), ...(process.env.CI ? ['--no-sandbox'] : [])],
    cwd: APP,
    env: {
      ...(process.env as Record<string, string>),
      DOOR_WEB_PROFILE: phoneProfile(served.fixture),
      DOOR_WEB_URL: `${served.url}/#pair=${served.newCode()}`,
      DOOR_WEB_WIDTH: '390',
    },
  })
}

type Counted = { prompted?: number }

test('after pairing the browser offers the install: the line shows, the tap prompts (#576)', async () => {
  test.skip(!served.fixture.hasPython, `no Python at ${served.fixture.python}`)
  const app = await openPaired()
  try {
    const page = await app.firstWindow()
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible({ timeout: 30_000 })
    await page.evaluate(() => {
      const w = window as unknown as Counted
      const e = Object.assign(new Event('beforeinstallprompt', { cancelable: true }), {
        prompt: async () => void (w.prompted = (w.prompted ?? 0) + 1),
      })
      window.dispatchEvent(e)
    })
    const install = page.getByRole('button', { name: 'Install the app' })
    await expect(install).toBeVisible()
    for (const theme of ['light', 'dark']) {
      await page.evaluate((t) => document.documentElement.setAttribute('data-theme', t), theme)
      if (process.env.SHOTS) await page.screenshot({ path: `${process.env.SHOTS}/install-android-${theme}.png` })
    }
    await install.click()
    expect(await page.evaluate(() => (window as unknown as Counted).prompted)).toBe(1)
    // the browser's event works once: the line is gone after the tap
    await expect(page.getByRole('region', { name: 'Install the app' })).toHaveCount(0)
  } finally {
    await app.close()
  }
})

test('an iPhone in Safari (WebKit) is told to tap Share, with no install button (#576)', async () => {
  test.skip(!served.fixture.hasPython, `no Python at ${served.fixture.python}`)
  const browser = await webkit.launch()
  try {
    const context = await browser.newContext({ ...devices['iPhone 13'] })
    const page = await context.newPage()
    await page.goto(`${served.url}/#pair=${served.newCode()}`)
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText('To install, tap Share, then Add to Home Screen.')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Install the app' })).toHaveCount(0)
    for (const theme of ['light', 'dark']) {
      await page.evaluate((t) => document.documentElement.setAttribute('data-theme', t), theme)
      if (process.env.SHOTS) await page.screenshot({ path: `${process.env.SHOTS}/install-iphone-${theme}.png` })
    }
  } finally {
    await browser.close()
  }
})
