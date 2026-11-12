// Records docs/demo/app.gif (`npm run record:gif`): the built app on made-up data (the demo, in a temp
// folder: never app/.demo, your profile/ or jobs/), driven like a person would, a frame on every repaint
// (Chromium's screencast); scripts/demo/app_gif.py turns the frames into the GIF. Light theme by emulation only, so the
// app's stored Appearance is left alone. No claude, no network: the demo's run is simulated.
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { _electron as electron, expect, test, type Locator, type Page } from '@playwright/test'
import { buildHome } from '../test/home-fixture'

const APP = resolve(__dirname, '..')
const fixture = buildHome()
const FRAMES = process.env.DOOR_GIF_FRAMES ?? join(fixture.scratch, 'frames')

test.skip(!fixture.hasPython, `no Python at ${fixture.python} (set DOOR_PYTHON)`)

/** A cursor drawn into the page (screenshots carry no real pointer), moved before each click. */
async function addCursor(page: Page) {
  await page.evaluate(() => {
    const c = document.createElement('div')
    c.id = 'demo-cursor'
    Object.assign(c.style, {
      position: 'fixed', left: '0', top: '0', width: '18px', height: '18px', borderRadius: '50%', zIndex: '99999',
      background: 'rgba(30, 30, 30, 0.35)', border: '2px solid rgba(255, 255, 255, 0.9)', pointerEvents: 'none',
      transform: 'translate(640px, 420px)', transition: 'transform 450ms ease-in-out',
    })
    document.body.appendChild(c)
  })
}

async function click(page: Page, target: Locator, pause = 700) {
  const box = await target.boundingBox()
  if (box) {
    // just below and right of the target's start, so the dot does not cover its words
    const x = box.x + Math.min(box.width - 6, 24)
    const y = box.y + box.height - 4
    await page.evaluate(([x, y]) => {
      const c = document.getElementById('demo-cursor')
      if (c) c.style.transform = `translate(${x - 9}px, ${y - 9}px)`
    }, [x, y])
    await page.waitForTimeout(550)
  }
  await target.click()
  await page.waitForTimeout(pause)
}

test('record the app', async () => {
  test.setTimeout(240_000)
  rmSync(FRAMES, { recursive: true, force: true })
  mkdirSync(FRAMES, { recursive: true })
  writeFileSync(join(fixture.scratch, 'claude-signed-in'), '') // the stand-in claude says it is signed in
  const app = await electron.launch({
    args: ['.'],
    cwd: APP,
    env: { ...(process.env as Record<string, string>), ...fixture.env, DOOR_DEMO_DIR: join(fixture.scratch, 'demo'), DOOR_DEMO_RUN_MS: '9000', DOOR_DEMO_DISCOVERY: 'off' },
  })
  const frames: { file: string; at: number }[] = []
  try {
    const page = await app.firstWindow()
    await page.emulateMedia({ colorScheme: 'light' })
    await app.evaluate(({ BrowserWindow }) => {
      const w = BrowserWindow.getAllWindows()[0]
      w.setContentSize(1240, 760)
      w.center()
    })
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('Senior Financial Controller').first()).toBeVisible()
    await expect(page.getByText('Claude is not signed in')).toHaveCount(0, { timeout: 30_000 })
    await addCursor(page)
    await page.waitForTimeout(500)

    const t0 = Date.now()
    // The screencast, not page.screenshot in a loop: that visibly flickers the window it captures.
    const cdp = await page.context().newCDPSession(page)
    cdp.on('Page.screencastFrame', (f: { data: string; sessionId: number }) => {
      const file = join(FRAMES, `${String(frames.length).padStart(5, '0')}.jpg`)
      writeFileSync(file, Buffer.from(f.data, 'base64'))
      frames.push({ file, at: Date.now() - t0 })
      void cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => undefined)
    })
    await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 92, everyNthFrame: 1 })

    await page.waitForTimeout(1800)
    // Find new jobs: the five steps, then the summary and the new matches
    await click(page, page.getByRole('complementary').getByRole('button', { name: 'Find new jobs' }))
    await expect(page.getByRole('heading', { level: 2, name: /new matches/ })).toBeVisible({ timeout: 40_000 })
    await page.waitForTimeout(2200)
    await click(page, page.getByRole('button', { name: 'View matches' }), 1800)
    // A posting, read in full
    await click(page, page.getByText('Senior Business Controller').first(), 2600)
    await page.mouse.wheel(0, 400)
    await page.waitForTimeout(1500)
    // Applications: the board, then the prepared one's PDFs
    await click(page, page.getByRole('navigation').getByRole('button', { name: 'Applications' }), 2200)
    await click(page, page.getByRole('button', { name: /Finance Manager/ }).first(), 1500)
    await click(page, page.getByRole('button', { name: 'See the application' }))
    await expect(page.locator('img.paper').first()).toBeVisible({ timeout: 20_000 })
    await page.waitForTimeout(2600)
    await click(page, page.getByRole('button', { name: /^CV · / }), 2800)
    // back to the matches
    await click(page, page.getByRole('navigation').getByRole('button', { name: 'Matches' }), 1500)

    await cdp.send('Page.stopScreencast').catch(() => undefined)
    writeFileSync(join(FRAMES, 'frames.json'), JSON.stringify(frames))
  } finally {
    await app.close()
  }
})
