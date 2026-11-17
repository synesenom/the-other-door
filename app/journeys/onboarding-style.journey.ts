// The wizard's CV style tick: offered only for a source with a look to copy, held until Save, and the build
// then runs on in the background beside the first search; the sidebar says when it is ready.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from './fixtures'
import { LAUNCH, onSourcesWithCv, pick, readToReview, reviewHeading, saveAndSearch, scratchFile, sourcesHeading, chosen } from './helpers/onboarding'
import type { Page } from '@playwright/test'

// A short CV: the stand-in print sets it on one page, as the build's stress renders need.
test.use({ worldOptions: { empty: true, persona: 'jonas' } })

const STYLED_PDF = resolve(__dirname, '..', '..', 'tests', 'tailoring', 'fixtures', 'styles', 'latex-classic.pdf')
const finding = (page: Page) => page.getByRole('heading', { name: 'Finding jobs', level: 1 })
const styleBox = (page: Page) => page.getByRole('checkbox', { name: 'Make my tailored CVs look like the CV I uploaded', exact: true })
/** Jonas's CV names no city: the review asks for it before Save. */
const chooseCity = (page: Page) => page.getByLabel('City', { exact: true }).selectOption('Aarhus')
const readyLine = (page: Page) => page.getByRole('button', { name: 'Your CV style is ready to compare', exact: true })

// The build runs in a process of its own, and the sidebar reads its state every 30 s.
test.setTimeout(300_000)

test('a CV with a style to copy: tick, Save, the search starts at once, the build is ready later and its line opens Profile → CV', async ({ page, world, os }) => {
  await expect(sourcesHeading(page)).toBeVisible(LAUNCH)
  await pick(page, os, [scratchFile(world, 'my-cv.pdf', readFileSync(STYLED_PDF))])
  await expect(chosen(page).getByText('my-cv.pdf', { exact: true })).toBeVisible()
  await readToReview(page)
  await expect(styleBox(page)).not.toBeChecked()
  await expect(page.getByText('Takes 2–5 minutes in the background.')).toBeVisible()
  expect(world.toolCalls('build_style')).toEqual([])

  await styleBox(page).check()
  await chooseCity(page)
  await saveAndSearch(page).click()
  await expect(finding(page)).toBeVisible(LAUNCH)
  expect(world.toolCalls('build_style')).toHaveLength(1)
  expect(world.toolCalls('save_cv')).toHaveLength(1)

  await expect(readyLine(page)).toBeVisible({ timeout: 240_000 })
  expect(world.exists('profile/style.next/cv.template.html')).toBe(true)
  await readyLine(page).click()
  await expect(page.getByLabel('Your CV (Markdown)')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Profile', exact: true })).toHaveAttribute('aria-current', 'page')
})

test('the tick left off starts no build', async ({ page, world, os }) => {
  await expect(sourcesHeading(page)).toBeVisible(LAUNCH)
  await pick(page, os, [scratchFile(world, 'my-cv.pdf', readFileSync(STYLED_PDF))])
  await readToReview(page)
  await expect(styleBox(page)).toBeVisible()
  await chooseCity(page)
  await saveAndSearch(page).click()
  await expect(finding(page)).toBeVisible(LAUNCH)
  expect(world.toolCalls('build_style')).toEqual([])
})

test('a CV typed or written in a file with no look to copy has no tick box', async ({ page, world, os }) => {
  await onSourcesWithCv(page, world, os)
  await readToReview(page)
  await expect(reviewHeading(page)).toBeVisible(LAUNCH)
  await expect(styleBox(page)).toHaveCount(0)
})
