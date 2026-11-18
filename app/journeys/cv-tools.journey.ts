// Profile → Master CV, its Sources: "Add a page", "Check again" and "Replace CV file…" in dialogs (enrich: propose,
// then add the ticked ones to cv.md, marked in the CV). The market report is in Analytics (analytics.journey.ts).
import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { argsOf, config, cvBox, expectChips, exists, openCv, readText } from './helpers/profile'
import { scratchFile } from './helpers/onboarding'

const expand = (page: Page) => page.getByRole('dialog', { name: 'Add a page' })
const again = (page: Page) => page.getByRole('dialog', { name: 'Check your pages again' })
const pages = (page: Page) => page.getByRole('list', { name: 'What your Master CV is read from' })
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
    await expect(page.getByRole('button', { name: /^Forget / })).toHaveCount(0) // no page read yet
    await readPage(page, 'mkl.example/talks')
    await expect(expand(page).getByRole('group', { name: 'Work Experience' }).getByRole('checkbox', { name: second })).toBeChecked({ timeout: 60_000 })
    expect(argsOf(world, 'enrich')).toEqual([expect.objectContaining({ urls: ['https://mkl.example/talks'] })])
    expect(argsOf(world, 'enrich')[0]).not.toHaveProperty('apply')
    expect(world.claudeCalls('enrich')).toHaveLength(1)
    await expect.poll(() => config(world).enrich_sources).toEqual(['https://mkl.example/talks']) // remembered at once
    expect(readText(world, 'profile/cv.md')).toBe(world.persona.cv) // nothing added yet
  })

  test('Add puts the ticked ones in cv.md, keeps cv.md.bak and marks them in the CV as it reads and in its text', { tag: '@core' }, async ({ page, world }) => {
    await openCv(page)
    await readPage(page, 'https://github.example/mkl')
    await expect(expand(page).getByRole('checkbox', { name: first })).toBeChecked({ timeout: 60_000 })
    if (await expand(page).getByRole('checkbox', { name: second }).count()) await expand(page).getByRole('checkbox', { name: second }).uncheck()
    await expand(page).getByRole('button', { name: 'Add 1 to my Master CV' }).click()
    await expect(expand(page)).toHaveCount(0, { timeout: 10_000 })
    await expect(page.locator('.cv-preview .md-added')).toHaveText('Bayesian hierarchical models (PyMC)')
    const cv = readText(world, 'profile/cv.md')
    expect(cv).toContain('- Bayesian hierarchical models (PyMC)')
    expect(cv.indexOf('- Bayesian hierarchical models (PyMC)')).toBeGreaterThan(cv.indexOf('## Skills'))
    expect(readText(world, 'profile/cv.md.bak')).toBe(world.persona.cv)
    expect(exists(world, 'profile/.enrich_proposals.json')).toBe(false)
    await page.getByRole('switch', { name: 'Preview' }).click()
    await expect(cvBox(page)).toHaveValue(cv)
    await expect(page.locator('.cv-backdrop .md-added')).toHaveText('- Bayesian hierarchical models (PyMC)')
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

test.describe('Replace CV file', () => {
  test('a new CV file proposes what it adds, and adding keeps everything the Master CV had', { tag: '@core' }, async ({ page, world, os }) => {
    await openCv(page)
    await os.nextOpen([scratchFile(world, 'newer-cv.md', `${world.persona.cv}\n## Talks\n\n- ${second}\n`)])
    await page.getByRole('group', { name: 'Sources' }).getByRole('button', { name: /^(Add a CV file|Replace CV file)…$/ }).click()
    const dialog = page.getByRole('dialog', { name: 'Add from your CV file' })
    await expect(dialog.getByRole('checkbox', { name: first })).toBeChecked({ timeout: 60_000 })
    expect(argsOf(world, 'enrich')).toEqual([expect.objectContaining({ files: [expect.stringMatching(/newer-cv\.md$/)] })])
    expect(world.toolCalls('draft_cv')).toHaveLength(0) // nothing drafted over the Master CV
    await dialog.getByRole('button', { name: /^Add \d+ to my Master CV$/ }).click()
    await expect(dialog).toHaveCount(0, { timeout: 10_000 })
    const cv = readText(world, 'profile/cv.md')
    for (const line of world.persona.cv.split('\n').filter((l) => l.trim())) expect(cv).toContain(line) // all it had
    expect(cv).toContain(first)
    await expect(page.locator('.cv-preview .md-added').first()).toBeVisible()
    await expect(pages(page).getByText('newer-cv.md', { exact: true })).toBeVisible() // the CV file from now on
  })
})
