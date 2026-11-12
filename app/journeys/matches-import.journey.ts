// "Add a job" from Matches: a link read and scored, a pasted ad, the duplicate, a link that cannot be
// fetched, and the imported ad opened. Checklist: inventory/jobs.md §7.
import { readdirSync } from 'node:fs'
import { join } from 'node:path'
import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { matchesLoaded, matchRows, METTE_ORDER } from './helpers/matches'

const URL = 'https://careers.solvang-energi-a-s.example/jobs/solvang-energi-forecasting-lead'
const PASTED = `Junior Forecast Analyst at Lysholm Varme. You will help our planners forecast district heating demand for the coming week, using Python and the weather data we already collect. Copenhagen office, three days a week.`

const addDialog = (page: Page) => page.getByRole('dialog', { name: 'Add a job' })
const imported = (page: Page) => page.getByRole('dialog', { name: 'Imported' })
const field = (page: Page, label: string) => addDialog(page).getByLabel(label, { exact: true })
const importButton = (page: Page) => addDialog(page).getByRole('button', { name: 'Import', exact: true })

async function openAdd(page: Page) {
  await matchesLoaded(page)
  await page.getByRole('button', { name: 'Add a job' }).click()
  await expect(addDialog(page)).toBeVisible()
}

function manualPostings(world: { home: string }): string[] {
  try {
    return readdirSync(join(world.home, 'jobs', 'postings', '2026-10-26', 'manual'))
  } catch {
    return []
  }
}

async function pasteAd(page: Page, text = PASTED) {
  await addDialog(page).getByRole('button', { name: 'Paste text' }).click()
  await field(page, 'Ad text').fill(text)
  await field(page, 'Title').fill('Junior Forecast Analyst')
  await field(page, 'Company').fill('Lysholm Varme')
}

test.describe('the form', () => {

  test('Paste text asks for the ad, a title and a company, and keeps what was typed', async ({ page, world }) => {
    await openAdd(page)
    await field(page, 'Title (optional)').fill('Junior Forecast Analyst')
    await field(page, 'Location (optional)').fill('Copenhagen')
    await addDialog(page).getByRole('button', { name: 'Paste text' }).click()
    await expect(addDialog(page).getByRole('button', { name: 'Paste text' })).toHaveAttribute('aria-pressed', 'true')
    await expect(addDialog(page).getByRole('button', { name: 'Link' })).toHaveAttribute('aria-pressed', 'false')
    await expect(field(page, 'Link')).toHaveCount(0)
    await expect(field(page, 'Title')).toHaveValue('Junior Forecast Analyst')
    await expect(field(page, 'Location (optional)')).toHaveValue('Copenhagen')
    await expect(importButton(page)).toBeDisabled()
    await field(page, 'Ad text').fill(PASTED)
    await expect(importButton(page)).toBeDisabled()
    await field(page, 'Company').fill('Lysholm Varme')
    await expect(importButton(page)).toBeEnabled()
    // back to Link: the title is still there
    await addDialog(page).getByRole('button', { name: 'Link' }).click()
    await expect(field(page, 'Title (optional)')).toHaveValue('Junior Forecast Analyst')
    await expect(field(page, 'Company (optional)')).toHaveValue('Lysholm Varme')
    expect(world.toolCalls('import_posting')).toEqual([])
  })
})

test.describe('importing', () => {
  test('a link is read, scored and shown', async ({ page, world }) => {
    await openAdd(page)
    world.faults({ tools: { import_posting: { delay_s: 2 } } })
    await field(page, 'Link').fill(URL)
    await importButton(page).click()
    await expect(addDialog(page).getByRole('status')).toHaveText('Reading and scoring the ad…')
    await expect(field(page, 'Link')).toBeDisabled()
    await expect(importButton(page)).toBeDisabled()
    await expect(addDialog(page).getByRole('button', { name: 'Cancel' })).toBeEnabled()
    const ad = world.ads['solvang-energi-forecasting-lead']
    await expect(imported(page).getByText(ad.title, { exact: true })).toBeVisible()
    await expect(imported(page).getByText('Solvang Energi A/S · Copenhagen (hybrid)', { exact: true })).toBeVisible()
    await expect(imported(page).getByText('0.90', { exact: true })).toBeVisible()
    await expect(imported(page).getByText(ad.reason, { exact: true })).toBeVisible()
    expect(world.toolCalls('import_posting').map((c) => c.args)).toEqual([expect.objectContaining({ url: URL })])
    expect(world.claudeCalls('read_ad')).toHaveLength(1)
    const id = world.toolCalls('show').at(-1)?.args?.job_id as string
    expect(id).toMatch(/^manual\./)
    expect(manualPostings(world)).toEqual([`${id}.json`])
    expect(world.readJson(`jobs/postings/2026-10-26/manual/${id}.json`)).toMatchObject({ title: ad.title, company: ad.company, url: URL, score: 0.9 })
  })

  test('Open shows the imported ad, kept open though the list does not hold it', async ({ page, world }) => {
    await openAdd(page)
    await field(page, 'Link').fill(URL)
    await importButton(page).click()
    await imported(page).getByRole('button', { name: 'Open' }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.getByRole('heading', { name: world.ads['solvang-energi-forecasting-lead'].title, level: 2 })).toBeVisible()
    await expect(page.getByRole('group', { name: 'Previous and next match' })).toHaveCount(0)
    await page.getByRole('button', { name: '← Matches' }).click()
    await expect(matchRows(page)).toHaveCount(METTE_ORDER.length)
  })

  test('a pasted ad is scored and shown', async ({ page, world }) => {
    await openAdd(page)
    await pasteAd(page)
    await field(page, 'Location (optional)').fill('Copenhagen')
    await importButton(page).click()
    await expect(imported(page).getByText('Junior Forecast Analyst', { exact: true })).toBeVisible()
    await expect(imported(page).getByText('Lysholm Varme · Copenhagen', { exact: true })).toBeVisible()
    await expect(imported(page).getByText('0.42', { exact: true })).toBeVisible()
    await expect(imported(page).getByText('Some overlap with the CV, but the role leans elsewhere.')).toBeVisible()
    expect(world.toolCalls('import_posting').map((c) => c.args)).toEqual([
      expect.objectContaining({ text: PASTED, title: 'Junior Forecast Analyst', company: 'Lysholm Varme', location: 'Copenhagen' }),
    ])
    expect(world.claudeCalls('read_ad')).toEqual([])
    expect(manualPostings(world)).toHaveLength(1)
  })

  test('the same ad twice is said, and "Import again anyway" replaces it', async ({ page, world }) => {
    await openAdd(page)
    await pasteAd(page)
    await importButton(page).click()
    await imported(page).getByRole('button', { name: 'Close' }).click()
    await page.getByRole('button', { name: 'Add a job' }).click()
    await pasteAd(page)
    await importButton(page).click()
    await expect(addDialog(page).getByText('You already imported this ad.', { exact: true })).toBeVisible()
    await expect(addDialog(page).getByRole('alert')).toHaveCount(0)
    await addDialog(page).getByRole('button', { name: 'Import again anyway' }).click()
    await expect(imported(page)).toBeVisible()
    expect(world.toolCalls('import_posting').map((c) => c.args?.force)).toEqual([false, false, true])
    expect(manualPostings(world)).toHaveLength(1)
  })
})

test.describe('failures', () => {
  test('a link that cannot be fetched is said, and the form can be sent again', async ({ page, world }) => {
    await openAdd(page)
    await field(page, 'Link').fill('https://jobs.nowhere.example/123')
    await importButton(page).click()
    await expect(addDialog(page).getByRole('alert')).toHaveText(/^could not fetch https:\/\/jobs\.nowhere\.example\/123: /)
    await expect(importButton(page)).toBeEnabled()
    await expect(field(page, 'Link')).toBeEnabled()
    expect(manualPostings(world)).toEqual([])
    await field(page, 'Link').fill(URL)
    await importButton(page).click()
    await expect(imported(page)).toBeVisible()
  })
})
