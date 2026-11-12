// The built app, a real door server and a temp DOOR_HOME: list the matches,
// open one, discard it with a reason and land on the next. Never touches the real jobs/ or profile/.
import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { _electron as electron, expect, test } from '@playwright/test'
import { buildHome, type Home } from '../test/home-fixture'

const APP = resolve(__dirname, '..')
const fixture = buildHome()

test.skip(!fixture.hasPython, `no Python at ${fixture.python} (set DOOR_PYTHON)`)

test('lists the matches, opens one, discards it with a reason and lands on the next', async () => {
  const app = await electron.launch({
    args: ['.', ...(process.env.CI ? ['--no-sandbox'] : [])],
    cwd: APP,
    env: { ...(process.env as Record<string, string>), ...fixture.env },
  })
  try {
    const page = await app.firstWindow()
    const rows = page.getByRole('listitem')
    await expect(rows).toHaveCount(2, { timeout: 60_000 })

    await rows.nth(1).getByRole('button').click()
    await expect(page.getByRole('heading', { name: 'BI Developer', level: 2 })).toBeVisible()

    await page.getByRole('button', { name: 'Not for me' }).click()
    await page.getByLabel('Why not?').fill('too far')
    await page.getByRole('button', { name: 'Discard' }).click()
    await expect(page.getByRole('heading', { name: 'Dataanalytiker', level: 2 })).toBeVisible()
    await page.getByRole('button', { name: '← Matches' }).click()
    await expect(rows).toHaveCount(1)
    await expect(rows.first()).toContainText('Dataanalytiker')

    const ledger = JSON.parse(readFileSync(join(fixture.home, 'jobs', 'applications.json'), 'utf8'))
    expect(ledger['jobindex.456'].status).toBe('discarded')
    expect(JSON.stringify(ledger['jobindex.456'].history)).toContain('too far')

    const fonts = await page.evaluate(async () => {
      await document.fonts.ready
      return {
        check: document.fonts.check('400 20px "Young Serif"'),
        loaded: [...document.fonts].some((f) => f.family.includes('Young Serif') && f.status === 'loaded'),
      }
    })
    expect(fonts).toEqual({ check: true, loaded: true })
  } finally {
    await app.close()
  }
})

// Each test below gets its own home and its own app, so the ledger of one never reaches another.
async function launch(own: Home) {
  return electron.launch({
    args: ['.', ...(process.env.CI ? ['--no-sandbox'] : [])],
    cwd: APP,
    env: { ...(process.env as Record<string, string>), ...own.env },
  })
}

test('marks a match applied and finds it in Applications', async () => {
  const own = buildHome()
  const app = await launch(own)
  try {
    const page = await app.firstWindow()
    const rows = page.getByRole('listitem')
    await expect(rows).toHaveCount(2, { timeout: 60_000 })
    await rows.nth(1).getByRole('button').click()
    await expect(page.getByRole('heading', { name: 'BI Developer', level: 2 })).toBeVisible()

    await page.getByRole('button', { name: 'Status', exact: true }).click()
    await page.getByRole('radio', { name: 'Applied', exact: true }).check()
    await page.getByRole('button', { name: 'Save' }).click()

    await expect(page.getByText('Applied: BI Developer. It is in Applications now.')).toBeVisible()
    await expect(rows).toHaveCount(1)
    await expect(rows.first()).toContainText('Dataanalytiker')

    await page.getByRole('navigation').getByRole('button', { name: 'Applications' }).click()
    await expect(page.getByRole('heading', { name: 'Applied', level: 2 }).first()).toBeVisible()
    await expect(page.getByRole('button', { name: /BI Developer/ })).toBeVisible()

    const ledger = JSON.parse(readFileSync(join(own.home, 'jobs', 'applications.json'), 'utf8'))
    expect(ledger['jobindex.456'].status).toBe('applied')
  } finally {
    await app.close()
  }
})

test('opening a new match makes it seen', async () => {
  const own = buildHome()
  const app = await launch(own)
  try {
    const page = await app.firstWindow()
    const rows = page.getByRole('listitem')
    await expect(rows).toHaveCount(2, { timeout: 60_000 })
    await expect(page.getByRole('img', { name: 'New since your last review' })).toHaveCount(2)
    await rows.first().getByRole('button').click()
    await page.getByRole('button', { name: '← Matches' }).click()
    await expect(page.getByRole('img', { name: 'New since your last review' })).toHaveCount(1)
    const seen = () => {
      try {
        return JSON.parse(readFileSync(join(own.home, 'jobs', 'last_review.json'), 'utf8')).seen ?? []
      } catch {
        return [] // not written yet
      }
    }
    await expect.poll(seen, { timeout: 30_000 }).toHaveLength(1)
  } finally {
    await app.close()
  }
})

test('imports a pasted ad and says it is not scored yet', async () => {
  const own = buildHome()
  const app = await launch(own)
  try {
    const page = await app.firstWindow()
    await expect(page.getByRole('listitem')).toHaveCount(2, { timeout: 60_000 })
    await page.getByRole('button', { name: 'Add a job' }).click()
    await page.getByRole('button', { name: 'Paste text' }).click()
    await page.getByLabel('Ad text').fill('We are hiring an analyst to work with SQL.')
    await page.getByLabel('Title', { exact: true }).fill('Analyst')
    await page.getByLabel('Company', { exact: true }).fill('Newco')
    await page.getByRole('button', { name: 'Import', exact: true }).click()
    await expect(page.getByText('Not scored yet', { exact: false })).toBeVisible({ timeout: 60_000 })
    await page.getByRole('button', { name: 'Open', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Analyst', level: 2 })).toBeVisible()
  } finally {
    await app.close()
  }
})
