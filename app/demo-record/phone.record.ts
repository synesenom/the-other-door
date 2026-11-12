// Records docs/demo/phone.gif (`npm run record:phone-gif`): the phone app against a real `door serve`
// on the demo's made-up data in a temp folder, in a 360 x 780 window (a small Android phone) with its own
// storage, driven like a thumb would (a drawn dot). The server runs through the demo GIFs' shim
// (scripts/demo/shim.py: fake job boards, canned scores, a ready-made CV and letter), so Find new jobs and
// Prepare play out for real in the app without the network or claude. Pairing, Find new jobs and its
// summary, the new matches, a posting, Prepare, Ready to send, Applications.
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { _electron as electron, expect, test, type Locator, type Page } from '@playwright/test'
import { phoneProfile, serveDemo } from '../e2e-web/serve-fixture'

test('record the phone app', async () => {
  test.setTimeout(240_000)
  const served = await serveDemo({ stubbed: true })
  writeFileSync(join(served.fixture.scratch, 'claude-signed-in'), '') // the stand-in claude says it is signed in
  const frames = process.env.DOOR_GIF_FRAMES ?? join(served.fixture.scratch, 'frames')
  rmSync(frames, { recursive: true, force: true })
  mkdirSync(frames, { recursive: true })
  const app = await electron.launch({
    args: [resolve(__dirname, '..', 'e2e-web', 'browser.cjs')],
    cwd: resolve(__dirname, '..'),
    env: { ...(process.env as Record<string, string>), DOOR_WEB_PROFILE: phoneProfile(served.fixture), DOOR_WEB_URL: served.url },
  })
  const shots: { file: string; at: number }[] = []
  let recording = true
  try {
    const page = await app.firstWindow()
    await page.emulateMedia({ colorScheme: 'light' })
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.setContentSize(360, 780))
    await expect(page.getByRole('heading', { name: 'Pair this phone' })).toBeVisible({ timeout: 30_000 })
    const dot = async () =>
      page.evaluate(() => {
        if (document.getElementById('demo-cursor')) return
        const c = document.createElement('div')
        c.id = 'demo-cursor'
        Object.assign(c.style, {
          position: 'fixed', left: '0', top: '0', width: '26px', height: '26px', borderRadius: '50%', zIndex: '99999',
          background: 'rgba(30, 30, 30, 0.28)', border: '2px solid rgba(255, 255, 255, 0.9)', pointerEvents: 'none',
          transform: 'translate(170px, 560px)', transition: 'transform 420ms ease-in-out',
        })
        document.body.appendChild(c)
      })
    const tap = async (target: Locator, pause = 900) => {
      await dot()
      const box = await target.boundingBox()
      if (box) {
        await page.evaluate(([x, y]) => {
          const c = document.getElementById('demo-cursor')
          if (c) c.style.transform = `translate(${x - 13}px, ${y - 13}px)`
        }, [box.x + Math.min(box.width / 2, 40), box.y + box.height / 2 + 6])
        await page.waitForTimeout(480)
      }
      await target.click()
      await page.waitForTimeout(pause)
    }
    const scroll = async (dy: number, pause = 900) => {
      await page.mouse.move(180, 400)
      await page.mouse.wheel(0, dy)
      await page.waitForTimeout(pause)
    }

    const t0 = Date.now()
    // DOOR_VIDEO_DIR: Chromium's own screencast, a frame on every repaint, for a smooth video (video_from_frames.py)
    const videoDir = process.env.DOOR_VIDEO_DIR
    const cast: { file: string; at: number }[] = []
    let cdp: Awaited<ReturnType<ReturnType<Page['context']>['newCDPSession']>> | null = null
    if (videoDir) {
      mkdirSync(videoDir, { recursive: true })
      cdp = await page.context().newCDPSession(page)
      cdp.on('Page.screencastFrame', (f: { data: string; sessionId: number }) => {
        const file = join(videoDir, `${String(cast.length).padStart(5, '0')}.jpg`)
        writeFileSync(file, Buffer.from(f.data, 'base64'))
        cast.push({ file, at: Date.now() - t0 })
        void cdp?.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => undefined)
      })
      await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 92, everyNthFrame: 1 })
    }
    const loop = (async () => {
      let n = 0
      while (recording && !process.env.DOOR_VIDEO_DIR) {
        const file = join(frames, `${String(n).padStart(5, '0')}.png`)
        await page.screenshot({ path: file, scale: 'css' }).catch(() => undefined)
        shots.push({ file, at: Date.now() - t0 })
        n += 1
        await new Promise((r) => setTimeout(r, 50))
      }
    })()

    await page.waitForTimeout(1200)
    // pairing: the code from `door serve pair`, typed in
    await tap(page.getByLabel('Pairing code'), 300)
    await page.keyboard.type(served.code, { delay: 90 })
    await page.waitForTimeout(400)
    await tap(page.getByRole('button', { name: 'Pair' }), 300)
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible({ timeout: 30_000 })
    await page.waitForTimeout(1800)
    // Find new jobs: the five steps run on the door machine, the phone follows them
    await tap(page.getByRole('main').getByRole('button', { name: 'Find new jobs' }), 300)
    await expect(page.getByRole('heading', { name: 'Finding jobs', level: 1 })).toBeVisible({ timeout: 20_000 })
    await expect(page.getByRole('button', { name: 'View matches' })).toBeVisible({ timeout: 180_000 })
    await page.waitForTimeout(1500)
    await scroll(400, 1800)
    await tap(page.getByRole('button', { name: 'View matches' }), 2000)
    // a new match, read, then prepared
    await tap(page.locator('.row').first(), 2000)
    await scroll(400, 1400)
    await tap(page.getByRole('button', { name: 'Prepare application' }), 300)
    const see = page.getByRole('button', { name: 'See the application' })
    await expect(page.locator('img.paper').first().or(see)).toBeVisible({ timeout: 120_000 })
    if (await see.isVisible()) await tap(see, 300)
    await expect(page.locator('img.paper').first()).toBeVisible({ timeout: 30_000 })
    await page.waitForTimeout(2200)
    await tap(page.getByRole('button', { name: /^CV · / }), 2400)
    // back out to Applications, where it now sits as Prepared
    await tap(page.getByRole('button', { name: /Posting/ }).first(), 1000)
    await tap(page.getByRole('button', { name: /Matches|Applications/ }).first(), 1200)
    await tap(page.getByRole('navigation').getByRole('button', { name: 'Applications' }), 2600)

    recording = false
    await loop
    writeFileSync(join(frames, 'frames.json'), JSON.stringify(shots))
    if (cdp && videoDir) {
      await cdp.send('Page.stopScreencast').catch(() => undefined)
      writeFileSync(join(videoDir, 'frames.json'), JSON.stringify(cast))
    }
  } finally {
    recording = false
    await app.close()
    served.stop()
  }
})
