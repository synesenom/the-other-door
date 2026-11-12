// The wizard's Reading step: draft_cv, infer_basics, suggest_titles and keywords, one after the other,
// each failing in turn (world.faults' claude map), or left with Back. Nothing but the scratch draft
// is written while it reads.
import { expect, test } from './fixtures'
import {
  backButton,
  continueButton,
  fold,
  LAUNCH,
  onSourcesWithCv,
  readingHeading,
  readingStep,
  reviewHeading,
  saveAndSearch,
} from './helpers/onboarding'
import type { Page } from '@playwright/test'

test.use({ worldOptions: { empty: true } })

const notice = (page: Page) => page.getByText(/^These could not be found in your sources: /)

test('Reading shows its five steps, the running one with its clock, while a slow draft is made', async ({ page, world, os }) => {
  await onSourcesWithCv(page, world, os)
  world.faults({ claude: { draft: { delay_s: 4 } } })
  await continueButton(page).click()
  await expect(readingHeading(page)).toBeVisible()
  await expect(page.getByText('It should take a few minutes.')).toBeVisible()
  await expect(page.getByRole('list', { name: 'Reading' }).getByRole('heading', { level: 2 })).toHaveText([
    'Drafting your CV',
    'Reading your details',
    'Finding titles that fit',
    'Choosing search terms',
    'Writing an example story',
  ])
  await expect(readingStep(page, 'Drafting your CV')).toHaveAttribute('aria-current', 'step')
  await expect(readingStep(page, 'Drafting your CV')).toContainText(/\d+ s$/)
  await expect(readingStep(page, 'Drafting your CV')).toContainText(/[1-9] s$/) // the clock moves
  await expect(backButton(page)).toBeEnabled()
  expect(world.exists('profile/config.json')).toBe(false)
  // The draft done, the next step runs; then the review opens by itself.
  await expect(reviewHeading(page)).toBeVisible(LAUNCH)
  expect(world.exists('profile/cv.draft.md')).toBe(true) // the only file reading writes
  expect(world.exists('profile/config.json')).toBe(false)
  expect(world.exists('profile/cv.md')).toBe(false)
})

test('a failed draft says the sources could not be read, with Try again and Go on without a draft', async ({ page, world, os }) => {
  await onSourcesWithCv(page, world, os)
  world.faults({ claude: { draft: { fail: 'You have reached your usage limit. It resets at 14:00.' } } })
  await continueButton(page).click()
  const alert = page.getByRole('alert')
  await expect(alert).toContainText('Your sources could not be read: ')
  await expect(alert).toContainText('You have reached your usage limit. It resets at 14:00.')
  await expect(alert.getByRole('button', { name: 'Try again', exact: true })).toBeVisible()
  await expect(alert.getByRole('button', { name: 'Go on without a draft', exact: true })).toBeVisible()
  await expect(readingStep(page, 'Drafting your CV')).toHaveAttribute('aria-current', 'step')
  await expect(readingStep(page, 'Drafting your CV')).not.toContainText(/\d+ s/) // the clock stops
  expect(world.claudeCalls('basics')).toEqual([]) // nothing else is asked
  expect(world.exists('profile/cv.draft.md')).toBe(false)
})

test('Go on without a draft: the review asks for everything and for the CV itself', async ({ page, world, os }) => {
  await onSourcesWithCv(page, world, os)
  world.faults({ claude: { draft: { fail: 'claude is overloaded' } } })
  await continueButton(page).click()
  await page.getByRole('button', { name: 'Go on without a draft', exact: true }).click()
  await expect(reviewHeading(page)).toBeVisible(LAUNCH)
  expect(world.toolCalls('infer_basics').map((c) => c.args?.markdown ?? null)).toEqual([null])
  await expect(notice(page)).toHaveText('These could not be found in your sources: your name, your email, your city, job titles. Fill them in below to finish.')
  expect(world.toolCalls('keywords')).toEqual([]) // no title, nothing to choose terms for
  // The CV fold is open, on the box, empty.
  await expect(fold(page, 'CV').locator('summary')).toContainText('No CV yet')
  await expect(page.getByLabel('Your CV', { exact: true })).toHaveValue('')
  await expect(page.getByRole('switch', { name: 'Preview' })).toHaveAttribute('aria-checked', 'false')
  await expect(saveAndSearch(page)).toBeDisabled()
  expect(world.exists('profile/config.json')).toBe(false)
})

test('when Claude cannot read the details, the review says so', async ({ page, world, os }) => {
  await onSourcesWithCv(page, world, os)
  world.faults({ claude: { basics: { fail: 'You have reached your usage limit.' } } })
  await continueButton(page).click()
  await expect(reviewHeading(page)).toBeVisible(LAUNCH)
  await expect(page.getByText(/usage limit/)).toBeVisible()
})

test('when Claude cannot suggest titles, the review says so', async ({ page, world, os }) => {
  await onSourcesWithCv(page, world, os)
  world.faults({ claude: { titles: { fail: 'claude is overloaded' } } })
  await continueButton(page).click()
  await expect(reviewHeading(page)).toBeVisible(LAUNCH)
  await expect(page.getByText(/claude is overloaded/)).toBeVisible()
})

test('when no search terms could be proposed, the review says why', async ({ page, world, os }) => {
  await onSourcesWithCv(page, world, os)
  world.faults({ claude: { keywords: { fail: 'claude is overloaded' } } })
  await continueButton(page).click()
  await expect(reviewHeading(page)).toBeVisible(LAUNCH)
  await expect(page.getByText(/^Claude could not propose search terms, so your titles are searched as they are: .*claude is overloaded/)).toBeVisible()
})

test('Back during reading stops it: reading again asks each question once', async ({ page, world, os }) => {
  await onSourcesWithCv(page, world, os)
  world.faults({ claude: { draft: { delay_s: 3 } } })
  await continueButton(page).click()
  await expect(readingHeading(page)).toBeVisible()
  await backButton(page).click()
  await continueButton(page).click()
  await expect(reviewHeading(page)).toBeVisible(LAUNCH)
  // The first reading was started earlier than the second: had it gone on, its calls are in by now.
  expect(world.toolCalls('infer_basics')).toHaveLength(1)
  expect(world.toolCalls('suggest_titles')).toHaveLength(1)
})
