// The Status dialog from a posting in Matches: "Not for me", Prepared, Applied, an interview,
// the notices it leaves on the list, and a busy ledger. The rest is StatusDialog.test.tsx's. Checklist:
// inventory/jobs.md §4 (and §2's notices).
import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { holdRun, matchesLoaded, matchRows, METTE_ORDER, notificationOpens, openRow, postingHeading, row, shownTitle } from './helpers/matches'

const GRID = 'gridwise-ml-engineer-remote'
const STATUS_WORDS = ['Not yet applied', 'Prepared', 'Applied', 'Interview', 'Ghosted', 'Rejected', 'Offer', 'Not for me']

const statusDialog = (page: Page, title: string) => page.getByRole('dialog', { name: `Status: ${title}` })
const radio = (page: Page, name: string | RegExp) => page.getByRole('dialog').getByRole('radio', { name, exact: typeof name === 'string' })
const save = (page: Page) => page.getByRole('dialog').getByRole('button', { name: 'Save' })
/** The notice a status change leaves (not the list's Loading…). */
const notice = (page: Page) => page.getByRole('main').getByRole('status').filter({ hasNotText: 'Loading…' })
const ledger = (world: { readJson: (p: string) => any }) => world.readJson('jobs/applications.json') as Record<string, any>

async function openStatus(page: Page, world: any, key: string) {
  await matchesLoaded(page)
  await openRow(page, world, key)
  await page.getByRole('button', { name: 'Status', exact: true }).click()
  await expect(statusDialog(page, shownTitle(world, key))).toBeVisible()
}

test.describe('"Not for me"', () => {

  test('Discard records the reason and opens the next match in its place', async ({ page, world }) => {
    await matchesLoaded(page)
    const id = world.jobId('nordisk-elnet-prognose')
    await openRow(page, world, 'nordisk-elnet-prognose')
    await page.getByRole('button', { name: 'Not for me' }).click()
    await page.getByLabel('Why not?').fill('Odense is too far')
    await page.getByRole('button', { name: 'Discard' }).click()
    await expect(notice(page)).toHaveText(`Not for me: ${shownTitle(world, 'nordisk-elnet-prognose')}.`)
    await expect(postingHeading(page, world, 'fjordpension-senior-ds')).toBeVisible()
    await expect(page.getByRole('group', { name: 'Previous and next match' })).toContainText('3 of 8')
    expect(world.toolCalls('set_status').map((c) => c.args)).toEqual([expect.objectContaining({ job_id: id, status: 'discarded', notes: 'Odense is too far' })])
    expect(ledger(world)[id]).toMatchObject({ status: 'discarded', history: [expect.objectContaining({ status: 'discarded', notes: 'Odense is too far' })] })
    // a step clears the notice; the discarded match is gone from the list
    await page.getByRole('button', { name: 'Next match' }).click()
    await expect(notice(page)).toHaveCount(0)
    await page.getByRole('button', { name: '← Matches' }).click()
    await expect(matchRows(page)).toHaveCount(METTE_ORDER.length - 1)
    await expect(row(page, world, 'nordisk-elnet-prognose')).toHaveCount(0)
  })
})

test.describe('the Status dialog', () => {
  test('opens on the current status, with every status to choose from', async ({ page, world }) => {
    await openStatus(page, world, GRID)
    const group = page.getByRole('radiogroup', { name: 'Status' })
    await expect(group.getByRole('radio')).toHaveCount(8)
    for (const word of STATUS_WORDS) await expect(radio(page, word)).toBeVisible()
    await expect(radio(page, 'Not yet applied')).toBeChecked()
    await expect(radio(page, 'Not yet applied')).toBeFocused()
    await expect(page.getByRole('radiogroup', { name: 'Kind of interview' })).toHaveCount(0)
    await expect(page.getByRole('dialog').getByLabel('Notes (optional)')).toBeVisible()
    await expect(save(page)).toBeEnabled()
  })

  test('Prepared moves the job to Applications', { tag: '@core' }, async ({ page, world }) => {
    await openStatus(page, world, GRID)
    await radio(page, 'Prepared').check()
    await save(page).click()
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible()
    await expect(notice(page)).toHaveText(`Prepared: ${shownTitle(world, GRID)}. It is in Applications now.`)
    await expect(row(page, world, GRID)).toHaveCount(0)
    expect(ledger(world)[world.jobId(GRID)].status).toBe('prepared')
  })

  test('Applied records the application', async ({ page, world }) => {
    await openStatus(page, world, 'fjordpension-senior-ds')
    await radio(page, 'Applied').check()
    await save(page).click()
    await expect(notice(page)).toHaveText(`Applied: ${shownTitle(world, 'fjordpension-senior-ds')}. It is in Applications now.`)
    const id = world.jobId('fjordpension-senior-ds')
    expect(world.toolCalls('set_status').map((c) => c.args)).toEqual([expect.objectContaining({ job_id: id, status: 'applied' })])
    expect(ledger(world)[id]).toMatchObject({ status: 'applied' })
    await expect(row(page, world, 'fjordpension-senior-ds')).toHaveCount(0)
  })

  test('Interview: screening needs the kind picked first', async ({ page, world }) => {
    await openStatus(page, world, GRID)
    await radio(page, 'Interview').check()
    const kinds = page.getByRole('radiogroup', { name: 'Kind of interview' })
    await expect(kinds.getByRole('radio')).toHaveCount(4)
    await expect(save(page)).toBeDisabled()
    await kinds.getByRole('radio', { name: /^Screening/ }).check()
    await expect(save(page)).toBeEnabled()
    await save(page).click()
    await expect(notice(page)).toHaveText(`Interview: ${shownTitle(world, GRID)}. It is in Applications now.`)
    expect(ledger(world)[world.jobId(GRID)].status).toBe('interview:screening')
  })
})

test.describe('a job already in play', () => {
  test('the dialog starts on the checked status', async ({ app, page, world }) => {
    await matchesLoaded(page)
    await notificationOpens(app, { screen: 'posting', jobId: world.jobId('pakkepost-causal-experimentation'), inPlay: false })
    await expect(postingHeading(page, world, 'pakkepost-causal-experimentation')).toBeVisible()
    await page.getByRole('button', { name: 'Status', exact: true }).click()
    await expect(radio(page, 'Interview')).toBeChecked()
    await expect(radio(page, 'Interview')).toBeFocused({ timeout: 5_000 })
  })

  test('the notice names a job that is not in the list', async ({ app, page, world }) => {
    await matchesLoaded(page)
    await notificationOpens(app, { screen: 'posting', jobId: world.jobId('skovlund-data-engineer-azure'), inPlay: false })
    await expect(postingHeading(page, world, 'skovlund-data-engineer-azure')).toBeVisible()
    await page.getByRole('button', { name: 'Status', exact: true }).click()
    await radio(page, 'Applied').check()
    await save(page).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    expect(ledger(world)[world.jobId('skovlund-data-engineer-azure')].status).toBe('applied')
    await expect(notice(page)).toHaveText('Applied: Data Engineer (Azure). It is in Applications now.', { timeout: 5_000 })
  })
})

test.describe('when the ledger cannot be written', () => {
  test('a run elsewhere holding the ledger is said in the dialog', async ({ page, world }) => {
    await matchesLoaded(page)
    const run = await holdRun(world)
    try {
      await expect(page.getByRole('heading', { name: 'Finding jobs', level: 1 })).toBeVisible()
      await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Matches' }).click()
      await openRow(page, world, GRID)
      await page.getByRole('button', { name: 'Status', exact: true }).click()
      await radio(page, 'Applied').check()
      await save(page).click()
      await expect(page.getByRole('dialog').getByRole('alert')).toHaveText(/^a run is in progress \(started \d\d:\d\d, pid \d+\); try again when it has finished$/)
      await expect(save(page)).toBeEnabled()
      expect(world.exists('jobs/applications.json') ? ledger(world)[world.jobId(GRID)] : undefined).toBeUndefined()
    } finally {
      await run.release()
    }
  })
})
