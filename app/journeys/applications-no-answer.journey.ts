// Applications, an application quiet too long (inventory/jobs.md §6, #89): the card has the warning mark with
// its words, and the opened application's Status records it as ghosted. The seed ages one ledger entry; the other journeys' ledger stays as it is.
import { writeFileSync } from 'node:fs'
import type { Page } from '@playwright/test'
import { join } from 'node:path'
import { expect, notice } from './fixtures'
import { card, column, ledgerEntry, narrow, openCard, ready, toApplications } from './helpers/applications'
import { before, test } from './helpers/settings'
import { NOW, type World } from '../test/world/build'

const SUNDLINE = 'Senior Data Scientist – Network Optimisation & Demand Forecasting Team'
const PAKKEPOST = 'Senior Data Scientist, Experimentation & Causal Inference'
const DAY = 86_400_000

/** The last event of a ledger entry moved to `daysAgo` days before the world's now, the ones before it four days apart. */
function age(world: World, key: string, daysAgo: number): void {
  const file = join(world.home, 'jobs', 'applications.json')
  const book = world.readJson('jobs/applications.json')
  const entry = book[world.jobId(key)]
  const n = entry.history.length
  entry.history.forEach((h: { at: string }, i: number) => {
    h.at = new Date(Date.parse(NOW) - (daysAgo + (n - 1 - i) * 4) * DAY).toISOString()
  })
  entry.updated_at = entry.history[n - 1].at
  writeFileSync(file, JSON.stringify(book, null, 2))
}

/** Opens the card and records it as ghosted through Status. */
async function markGhosted(page: Page, title: string): Promise<void> {
  await openCard(page, title)
  await page.getByRole('button', { name: 'Status…', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: `What happened: ${title}` })
  await dialog.getByRole('radio', { name: 'Ghosted', exact: true }).check()
  await dialog.getByRole('button', { name: 'Save' }).click()
  await expect(notice(page)).toContainText('Ghosted')
}

test.describe('an applied card silent for 50 days', () => {
  test.use({ seed: before((world) => age(world, 'sundline-network-optimisation', 50)) })

  test('says so, and Status records it as ghosted', async ({ page, world }) => {
    await toApplications(page)
    const applied = column(page, 'Applied')
    await expect(card(applied, SUNDLINE).getByRole('img', { name: 'No answer in 45 days' })).toBeVisible()
    // only this card is quiet too long
    await expect(page.getByRole('group', { name: 'Applications board' }).getByRole('img', { name: /^(No answer|Not sent) in/ })).toHaveCount(1)

    await markGhosted(page, SUNDLINE)
    await expect(applied.getByRole('button')).toHaveCount(0)
    await expect(card(column(page, 'Closed'), SUNDLINE)).toContainText('ghosted')
    const entry = ledgerEntry(world, 'sundline-network-optimisation')
    expect(entry?.status).toBe('ghosted')
    const last = world.readJson('jobs/applications.json')[world.jobId('sundline-network-optimisation')].history.at(-1)
    // dated today: the world's today, where the server's clock starts
    expect(new Date(last.at).toDateString()).toBe(new Date(NOW).toDateString())
  })

  test('narrow: the card has the mark', async ({ app, page }) => {
    await ready(page)
    await narrow(app, page)
    await page.getByRole('navigation').getByRole('button', { name: 'Applications', exact: true }).click()
    await expect(card(page, SUNDLINE).getByRole('img', { name: 'No answer in 45 days' })).toBeVisible()
  })
})

test.describe('an interview round silent for 50 days', () => {
  test.use({ seed: before((world) => age(world, 'pakkepost-causal-experimentation', 50)) })

  test('keeps its rounds, has the mark after 21 days, and Status records it as ghosted', async ({ page, world }) => {
    await toApplications(page)
    const interviewing = column(page, 'Interviewing')
    await expect(card(interviewing, PAKKEPOST)).toContainText('technical')
    await expect(card(interviewing, PAKKEPOST).getByRole('img', { name: 'No answer in 21 days' })).toBeVisible()
    await markGhosted(page, PAKKEPOST)
    await expect(card(column(page, 'Closed'), PAKKEPOST)).toContainText('ghosted')
    expect(ledgerEntry(world, 'pakkepost-causal-experimentation')?.status).toBe('ghosted')
  })
})
