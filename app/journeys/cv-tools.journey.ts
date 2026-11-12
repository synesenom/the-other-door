// Profile → CV, the pages above the editor: "Add a page" and "Check again" in dialogs (enrich: propose,
// then add the ticked ones to cv.md, marked in the CV), "What should I learn?" (skill_gaps: a report saved in upskill/) and the market report
// folded at the foot (market: counts, a plan for missing skills, titles to add to the search).
import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { argsOf, config, cvBox, expectChips, exists, openCv, readText } from './helpers/profile'

const expand = (page: Page) => page.getByRole('dialog', { name: 'Add a page' })
const again = (page: Page) => page.getByRole('dialog', { name: 'Check your pages again' })
const pages = (page: Page) => page.getByRole('list', { name: 'Pages your CV is read from' })
const gaps = (page: Page) => page.getByRole('region', { name: 'What should I learn?' })
const marketFold = (page: Page) => page.getByRole('button', { name: /What the ads asked for this month/ })
const first = 'Bayesian hierarchical models (PyMC)'
const second = 'Gave a talk on probabilistic load forecasting at PyData Copenhagen 2024.'

async function readPage(page: Page, url: string) {
  await page.getByRole('button', { name: 'Add a page' }).click()
  await expand(page).getByLabel('Which page?').fill(url)
  await expand(page).getByRole('button', { name: 'Read it' }).click()
}

test.describe('Add a page', () => {
  test('reads the page asked for, remembers it, and proposes what the CV lacks, all ticked', async ({ page, world }) => {
    await openCv(page)
    await expect(pages(page)).toHaveCount(0)
    await readPage(page, 'mkl.example/talks')
    await expect(expand(page).getByRole('group', { name: 'Work Experience' }).getByRole('checkbox', { name: second })).toBeChecked({ timeout: 60_000 })
    expect(argsOf(world, 'enrich')).toEqual([expect.objectContaining({ urls: ['https://mkl.example/talks'] })])
    expect(argsOf(world, 'enrich')[0]).not.toHaveProperty('apply')
    expect(world.claudeCalls('enrich')).toHaveLength(1)
    await expect.poll(() => config(world).enrich_sources).toEqual(['https://mkl.example/talks']) // remembered at once
    expect(readText(world, 'profile/cv.md')).toBe(world.persona.cv) // nothing added yet
  })

  test('Add puts the ticked ones in cv.md, keeps cv.md.bak and marks them in the editor', { tag: '@core' }, async ({ page, world }) => {
    await openCv(page)
    await readPage(page, 'https://github.example/mkl')
    await expect(expand(page).getByRole('checkbox', { name: first })).toBeChecked({ timeout: 60_000 })
    if (await expand(page).getByRole('checkbox', { name: second }).count()) await expand(page).getByRole('checkbox', { name: second }).uncheck()
    await expand(page).getByRole('button', { name: 'Add 1 to my CV' }).click()
    await expect(expand(page)).toHaveCount(0, { timeout: 10_000 })
    await expect(page.locator('.cv-backdrop .md-added')).toHaveText('- Bayesian hierarchical models (PyMC)')
    const cv = readText(world, 'profile/cv.md')
    expect(cv).toContain('- Bayesian hierarchical models (PyMC)')
    expect(cv.indexOf('- Bayesian hierarchical models (PyMC)')).toBeGreaterThan(cv.indexOf('## Skills'))
    expect(readText(world, 'profile/cv.md.bak')).toBe(world.persona.cv)
    expect(exists(world, 'profile/.enrich_proposals.json')).toBe(false)
    await expect(cvBox(page)).toHaveValue(cv)
    await expect(pages(page)).toContainText('github.example/mkl')
  })
})

test.describe('the pages read before', () => {
  test.use({ worldOptions: { config: { enrich_sources: ['https://github.example/mkl', 'https://mkl.example/talks'] } } })

  test('Check again reads them all and names the page of each proposal', async ({ page, world }) => {
    await openCv(page)
    await page.getByRole('button', { name: 'Check again' }).click()
    await expect(again(page).getByRole('checkbox', { name: `${first} · from https://github.example/mkl` })).toBeChecked({ timeout: 60_000 })
    expect(argsOf(world, 'enrich')).toEqual([expect.objectContaining({ urls: ['https://github.example/mkl', 'https://mkl.example/talks'] })])
  })

  test('a page is forgotten by its ×', async ({ page, world }) => {
    await openCv(page)
    await page.getByRole('button', { name: 'Forget https://mkl.example/talks' }).click()
    await expect.poll(() => config(world).enrich_sources).toEqual(['https://github.example/mkl'])
  })
})

// off for now (#480: CvEditor's `extras`); on again with the feature
test.describe.skip('What should I learn?', () => {
  test('makes a plan for the role targets, shows it and saves it in upskill/', async ({ page, world }) => {
    await openCv(page)
    await page.getByRole('button', { name: 'What should I learn?' }).click()
    await expect(page.getByRole('button', { name: 'What should I learn?' })).toHaveAttribute('aria-expanded', 'true')
    await expectChips(page, 'Roles or skills', world.persona.roleTargets)
    await expect(gaps(page).getByRole('checkbox', { name: 'Also my three best matches' })).not.toBeChecked()
    await expect(gaps(page).getByText('One Claude call on your plan, with web search for courses.')).toBeVisible()
    await gaps(page).getByRole('button', { name: 'Make my plan' }).click()
    await expect(gaps(page).getByRole('heading', { name: 'Skill-gap report', level: 2 })).toBeVisible()
    await expect(gaps(page).getByRole('heading', { name: 'Gaps', level: 3 })).toBeVisible()
    await expect(gaps(page).getByRole('listitem').filter({ hasText: /^Kubernetes/ })).toContainText('asked for by three of the five ads.')
    await expect(gaps(page).getByText('Saved as report-2026-10-26.md in upskill/.')).toBeVisible()
    expect(readText(world, 'upskill/report-2026-10-26.md')).toContain('Kubernetes')
    expect(argsOf(world, 'skill_gaps')).toEqual([expect.objectContaining({ targets: world.persona.roleTargets })])
    expect(argsOf(world, 'skill_gaps')[0]).not.toHaveProperty('top')
    expect(world.claudeCalls('gaps')).toHaveLength(1)
    await gaps(page).getByRole('heading', { name: 'Skill-gap report' }).scrollIntoViewIfNeeded()
    await gaps(page).getByRole('button', { name: 'Make another plan' }).click()
    await expectChips(page, 'Roles or skills', world.persona.roleTargets)
    await expect(gaps(page).getByRole('button', { name: 'Make my plan' })).toBeEnabled()
  })
})

// off for now (#480: CvEditor's `extras`); on again with the feature
test.describe.skip('What the ads asked for this month', () => {
  test('counts the ads when opened, once', async ({ page, world }) => {
    await openCv(page)
    await marketFold(page).click()
    await expect(marketFold(page)).toHaveAttribute('aria-expanded', 'true')
    await expect(page.getByText('23 ads read, 22 scored, 16 at your minimum score.')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Most asked for', level: 3 })).toBeVisible()
    const skills = page.getByRole('listitem', { name: 'Python', exact: true }).locator('..').getByRole('listitem')
    await expect(skills).toHaveCount(8)
    await expect(page.getByRole('listitem', { name: 'Python', exact: true })).toHaveText('Python · 86% of the ads · in your CV')
    await expect(page.getByRole('listitem', { name: 'SQL', exact: true })).toHaveText('SQL · 45% of the ads · in your CV')
    await expect(page.getByText('What kept 4 ads just under your minimum: Amplitude, Azure Data Factory, budget responsibility, consulting, data quality testing, media analytics, people management, product analytics, recommender systems, Synapse.')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Titles your search does not cover', level: 3 })).toBeVisible()
    await expect(page.getByText('Datafaglig konsulent med fokus på prognoser og befolkningsdata (1)')).toBeVisible()
    await expect(page.getByRole('button', { name: /^Make a plan for/ })).toHaveCount(0) // every top skill is in the CV
    expect(argsOf(world, 'market')).toEqual([expect.objectContaining({ save: false })])
    expect(exists(world, 'jobs/market')).toBe(false) // no report written
    expect(exists(world, 'jobs/skill_aliases.json')).toBe(true) // the new skill names, grouped once
    await marketFold(page).evaluate((el) => el.scrollIntoView({ block: 'start' }))
    // closed and opened again: the same report, not asked again
    await marketFold(page).click()
    await expect(page.getByText('Counts the ads of the last 30 days. New skill names may need one short Claude call on your plan.')).toBeVisible()
    await marketFold(page).click()
    await expect(page.getByText('23 ads read, 22 scored, 16 at your minimum score.')).toBeVisible()
    expect(world.toolCalls('market')).toHaveLength(1)
  })

  test('Add these titles to my search asks first, then adds them to the search keywords', async ({ page, world }) => {
    const before = config(world)
    await openCv(page)
    await marketFold(page).click()
    await page.getByRole('button', { name: 'Add these titles to my search' }).click()
    const dialog = page.getByRole('dialog', { name: 'Add these titles to your search?' })
    await expect(dialog).toHaveText(/The job boards will also be searched for Datafaglig konsulent med fokus på prognoser og befolkningsdata\./)
    await dialog.getByRole('button', { name: 'Cancel' }).click()
    await expect(dialog).toHaveCount(0)
    await page.getByRole('button', { name: 'Add these titles to my search' }).click()
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    expect(world.toolCalls('init_profile')).toEqual([])
    await page.getByRole('button', { name: 'Add these titles to my search' }).click()
    await dialog.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(page.getByText('Added to your search keywords.')).toBeVisible()
    const title = 'Datafaglig konsulent med fokus på prognoser og befolkningsdata'
    expect(config(world)).toEqual({ ...before, search_keywords: [...world.persona.searchKeywords, title] })
    expect(argsOf(world, 'init_profile')).toEqual([{ search_keywords: [...world.persona.searchKeywords, title] }])
  })

  test('titles added from the report show in the details', async ({ page }) => {
    await openCv(page)
    await marketFold(page).click()
    await page.getByRole('button', { name: 'Add these titles to my search' }).click()
    await page.getByRole('dialog', { name: 'Add these titles to your search?' }).getByRole('button', { name: 'Add', exact: true }).click()
    await expect(page.getByText('Added to your search keywords.')).toBeVisible()
    await page.getByRole('group', { name: 'Part of the profile' }).getByRole('button', { name: 'Details', exact: true }).click()
    await expect(
      page.getByRole('list', { name: 'Search keywords, chosen' }).getByRole('listitem').filter({ hasText: 'Datafaglig konsulent med fokus på prognoser og befolkningsdata' }),
    ).toHaveCount(1, { timeout: 5_000 })
  })

  test('a report that failed is asked again when reopened', async ({ page, world }) => {
    await openCv(page)
    world.faults({ tools: { market: { error: 'profile/companies.json: invalid JSON — Expecting value', once: true } } })
    await marketFold(page).click()
    await expect(page.getByRole('alert')).toBeVisible()
    await marketFold(page).click()
    await marketFold(page).click()
    await expect(page.getByText('23 ads read, 22 scored, 16 at your minimum score.')).toBeVisible({ timeout: 10_000 })
  })
})
