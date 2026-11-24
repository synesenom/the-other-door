// "Add a job" from Matches: a link read and scored, a pasted ad read (and one whose title and company are asked),
// the duplicate, a link that cannot be fetched, and the imported ad opened. Checklist: inventory/jobs.md §7.
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
  await page.getByRole('button', { name: 'Add a job…' }).click()
  await expect(addDialog(page)).toBeVisible()
}

function manualPostings(world: { home: string }): string[] {
  try {
    return readdirSync(join(world.home, 'jobs', 'postings', '2026-10-26', 'manual'))
  } catch {
    return []
  }
}

/** Pastes PASTED, an ad that names its title and company in a way the stand-in Claude does not read: both are asked, and filled in. */
async function pasteAd(page: Page) {
  await addDialog(page).getByRole('button', { name: 'Paste text' }).click()
  await field(page, 'Ad text').fill(PASTED)
  await importButton(page).click()
  await expect(addDialog(page).getByText('The title and company could not be found in the ad. Fill them in.', { exact: true })).toBeVisible()
  await field(page, 'Title').fill('Junior Forecast Analyst')
  await field(page, 'Company').fill('Lysholm Varme')
}

test.describe('the form', () => {

  test('Link asks only for the link, Paste text only for the ad', async ({ page, world }) => {
    await openAdd(page)
    await expect(addDialog(page).getByRole('textbox')).toHaveCount(1)
    await expect(field(page, 'Link')).toBeVisible()
    await addDialog(page).getByRole('button', { name: 'Paste text' }).click()
    await expect(addDialog(page).getByRole('button', { name: 'Paste text' })).toHaveAttribute('aria-pressed', 'true')
    await expect(addDialog(page).getByRole('textbox')).toHaveCount(1)
    await expect(importButton(page)).toBeDisabled()
    await field(page, 'Ad text').fill(PASTED)
    await expect(importButton(page)).toBeEnabled()
    // back to Link: only the link is asked
    await addDialog(page).getByRole('button', { name: 'Link' }).click()
    await expect(addDialog(page).getByRole('textbox')).toHaveCount(1)
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
    await expect(imported(page).getByText('90%', { exact: true })).toBeVisible()
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

  test('a pasted ad is read for its title, company and place, scored and shown', async ({ page, world }) => {
    const ad = world.ads['solvang-energi-forecasting-lead']
    const text = `${ad.title}\n\n${ad.description}`
    await openAdd(page)
    await addDialog(page).getByRole('button', { name: 'Paste text' }).click()
    await field(page, 'Ad text').fill(text)
    await importButton(page).click()
    await expect(imported(page).getByText(ad.title, { exact: true })).toBeVisible()
    await expect(imported(page).getByText(`${ad.company} · ${ad.location}`, { exact: true })).toBeVisible()
    expect(world.toolCalls('import_posting').map((c) => c.args)).toEqual([expect.objectContaining({ text })])
    expect(world.claudeCalls('read_ad')).toHaveLength(1)
    expect(manualPostings(world)).toHaveLength(1)
  })

  test('a pasted ad whose title and company cannot be found asks for them, and only them', async ({ page, world }) => {
    await openAdd(page)
    await pasteAd(page)
    expect(manualPostings(world)).toEqual([])
    await expect(addDialog(page).getByRole('textbox')).toHaveCount(3)
    await importButton(page).click()
    await expect(imported(page).getByText('Junior Forecast Analyst', { exact: true })).toBeVisible()
    await expect(imported(page).getByText('Lysholm Varme', { exact: true })).toBeVisible()
    await expect(imported(page).getByText('42%', { exact: true })).toBeVisible()
    await expect(imported(page).getByText('Some overlap with the CV, but the role leans elsewhere.')).toBeVisible()
    expect(world.toolCalls('import_posting').map((c) => c.args)).toEqual([
      expect.objectContaining({ text: PASTED }),
      expect.objectContaining({ text: PASTED, title: 'Junior Forecast Analyst', company: 'Lysholm Varme' }),
    ])
    expect(manualPostings(world)).toHaveLength(1)
  })

  test('the same ad twice is said, and "Import again anyway" replaces it', async ({ page, world }) => {
    await openAdd(page)
    await pasteAd(page)
    await importButton(page).click()
    await imported(page).getByRole('button', { name: 'Close' }).click()
    await page.getByRole('button', { name: 'Add a job…' }).click()
    await pasteAd(page)
    await importButton(page).click()
    await expect(addDialog(page).getByText('You already imported this ad.', { exact: true })).toBeVisible()
    await expect(addDialog(page).getByRole('alert')).toHaveCount(0)
    await addDialog(page).getByRole('button', { name: 'Import again anyway' }).click()
    await expect(imported(page)).toBeVisible()
    expect(world.toolCalls('import_posting').map((c) => c.args?.force)).toEqual([false, false, false, false, true])
    expect(manualPostings(world)).toHaveLength(1)
  })
})

test.describe('failures', () => {
  test('a link that cannot be fetched turns to Paste text, says why, and the ad keeps the link', async ({ page, world }) => {
    await openAdd(page)
    await field(page, 'Link').fill('https://jobs.nowhere.example/123')
    await importButton(page).click()
    await expect(addDialog(page).getByText("That page could not be read: it may need a sign-in. Paste the ad's text here.")).toBeVisible()
    await expect(addDialog(page).getByRole('button', { name: 'Paste text' })).toHaveAttribute('aria-pressed', 'true')
    await expect(addDialog(page).getByRole('alert')).toHaveCount(0)
    expect(manualPostings(world)).toEqual([])
    await expect(addDialog(page).getByRole('textbox')).toHaveCount(1)
    await field(page, 'Ad text').fill(PASTED)
    await importButton(page).click()
    await field(page, 'Title').fill('Junior Forecast Analyst')
    await field(page, 'Company').fill('Lysholm Varme')
    await importButton(page).click()
    await expect(imported(page)).toBeVisible()
    expect(world.toolCalls('import_posting').at(-1)?.args).toEqual(expect.objectContaining({ url: 'https://jobs.nowhere.example/123', title: 'Junior Forecast Analyst' }))
  })
})
