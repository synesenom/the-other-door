// The phone app at narrow, tall sizes (#303): from a small 320-wide phone to a 22:9 one. On each, every
// main screen fits its width (nothing scrolls sideways) and the tab bar stays on screen. With SHOTS set,
// each screen is also saved there to look at.
import { resolve } from 'node:path'
import { _electron as electron, expect, test } from '@playwright/test'
import { phoneProfile, serveDemo, type Served } from './serve-fixture'

const SIZES = [
  { w: 320, h: 640 },
  { w: 360, h: 880 }, // 22:9
  { w: 375, h: 667 },
  { w: 430, h: 932 },
]
// the phone's three: the profile is changed on the computer running The other door
const TABS = ['Matches', 'Applications', 'Settings']

let served: Served
test.beforeAll(async () => {
  served = await serveDemo()
})
test.afterAll(() => served?.stop())

test('every main screen fits narrow, tall windows', async () => {
  test.skip(!served.fixture.hasPython, `no Python at ${served.fixture.python}`)
  const app = await electron.launch({
    args: [resolve(__dirname, 'browser.cjs'), ...(process.env.CI ? ['--no-sandbox'] : [])],
    cwd: resolve(__dirname, '..'),
    env: { ...(process.env as Record<string, string>), DOOR_WEB_PROFILE: phoneProfile(served.fixture), DOOR_WEB_URL: `${served.url}/#pair=${served.code}` },
  })
  try {
    const page = await app.firstWindow()
    await page.emulateMedia({ colorScheme: 'light' })
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible({ timeout: 30_000 })
    for (const { w, h } of SIZES) {
      await app.evaluate(({ BrowserWindow }, [w, h]) => BrowserWindow.getAllWindows()[0]!.setContentSize(w, h), [w, h])
      await page.waitForFunction(([w]) => window.innerWidth === w, [w])
      for (const tab of TABS) {
        await page.getByRole('navigation').getByRole('button', { name: tab }).click()
        await expect(page.getByRole('heading', { name: tab, level: 1 })).toBeVisible()
        await page.waitForTimeout(600)
        const fit = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth }))
        expect(fit.scroll, `${tab} at ${w}x${h} scrolls sideways`).toBeLessThanOrEqual(fit.inner)
        // nothing cut off at the edge either (a panel that hides its overflow does not scroll the page)
        const cut = await page.evaluate(() =>
          [...document.querySelectorAll('button, h1, h2, input, select, textarea, a')]
            .filter((el) => {
              const r = el.getBoundingClientRect()
              return r.width > 0 && r.height > 0 && (r.right > window.innerWidth + 1 || r.left < -1)
            })
            .map((el) => (el.textContent || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 40)),
        )
        expect(cut, `${tab} at ${w}x${h}: cut off at the edge`).toEqual([])
        const bar = await page.getByRole('navigation').boundingBox()
        expect(bar && bar.y + bar.height <= h + 1, `${tab} at ${w}x${h}: the tab bar is off screen`).toBe(true)
        if (process.env.SHOTS) await page.screenshot({ path: `${process.env.SHOTS}/${w}x${h}-${tab}.png` })
      }
    }
  } finally {
    await app.close()
  }
})
