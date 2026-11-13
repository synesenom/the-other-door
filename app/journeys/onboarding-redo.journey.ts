// Drafting again (Profile → CV, no CV yet: "Draft it from your CV file or pages"): the same wizard on a profile that
// exists, prefilled, with a way back out; and the wizard in a narrow window.
import { rmSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from './fixtures'
import {
  backButton,
  continueButton,
  fold,
  LAUNCH,
  narrow,
  pick,
  rawCv,
  reason,
  reviewHeading,
  saveButton,
  sourcesHeading,
  titleBox,
  toReview,
} from './helpers/onboarding'
import { type World } from '../test/world/build'
import type { Page } from '@playwright/test'

async function setUpAgain(page: Page, world: World) {
  rmSync(join(world.home, 'profile', 'cv.md')) // the wizard is offered again while there is no CV
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible(LAUNCH)
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Profile', exact: true }).click()
  await page.getByRole('group', { name: 'Part of the profile' }).getByRole('button', { name: 'CV', exact: true }).click()
  await page.getByRole('button', { name: 'Draft it from your CV file or pages', exact: true }).click()
  await expect(sourcesHeading(page)).toBeVisible(LAUNCH)
}

test.describe('set up again', () => {
  test.use({ worldOptions: { persona: 'mette' } })

  test('Draft it again opens the sources with the answers kept, and Back', async ({ page, world }) => {
    await setUpAgain(page, world)
    await expect(page.getByText('Your answers stay.', { exact: true })).toBeVisible()
    await expect(page.getByRole('list', { name: 'Progress' }).locator('[aria-current="step"]')).toHaveAttribute('aria-label', 'Step 1 of 3')
    await expect(backButton(page)).toBeEnabled()
    await expect(continueButton(page)).toBeDisabled()
    await expect(page.getByRole('navigation')).toHaveCount(0)
    expect(world.toolCalls('draft_cv')).toEqual([])
  })

  test('a redo reads the new sources: the saved answers stay, the new CV is saved, and no run starts', { tag: '@core' }, async ({ page, world, os }) => {
    await setUpAgain(page, world)
    await pick(page, os, [rawCv(world)])
    await continueButton(page).click()
    await expect(reviewHeading(page)).toBeVisible(LAUNCH)
    await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Mette Kjær Larsen')
    await expect(fold(page, 'CV').locator('summary')).toContainText('Ready')
    // The saved titles come first, the new suggestions after them.
    await expect(titleBox(page, 'Senior Data Scientist')).toBeChecked()
    expect(world.toolCalls('suggest_titles')[0].args?.titles).toEqual(world.persona.roleTargets)
    await saveButton(page).click()
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible(LAUNCH)
    expect(world.toolCalls('save_cv')).toHaveLength(1)
    expect(world.exists('profile/cv.md')).toBe(true)
    expect(world.exists('profile/cv.md.bak')).toBe(false) // there was none to keep
    expect(world.toolCalls('find_jobs')).toEqual([])
    expect(world.readJson('profile/config.json').min_score).toBe(0.65) // what the wizard does not ask stays
  })
})

test.describe('narrow window', () => {
  test.use({ worldOptions: { empty: true } })

  test('in a narrow window the review is the same form, and saves the same', async ({ app, page, world, os }) => {
    await toReview(page, world, os)
    await narrow(app, page)
    await expect(page.getByLabel('City', { exact: true })).toHaveValue('Copenhagen')
    await expect(page.getByRole('group', { name: 'Find employers on' }).getByRole('checkbox')).toHaveCount(1) // LinkedIn, the one source serving Copenhagen
    await expect(reason(page)).toHaveCount(0)
    await page.getByRole('button', { name: 'Save and start searching', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Finding jobs', level: 1 })).toBeVisible(LAUNCH)
    expect(world.readJson('profile/config.json').location).toBe('Copenhagen')
  })
})

test.describe('a config.json the app cannot read', () => {
  test.use({ worldOptions: { persona: 'mette', config: { foo: 1 } } })

  test('an invalid config.json opens the wizard as a first launch, and reading says what is wrong with it', async ({ page, os, world }) => {
    await expect(sourcesHeading(page)).toBeVisible(LAUNCH)
    await expect(backButton(page)).toHaveCount(0)
    await pick(page, os, [rawCv(world)])
    await continueButton(page).click()
    await expect(page.getByRole('alert')).toContainText('foo — Extra inputs are not permitted')
    expect(world.claudeCalls('draft')).toEqual([]) // no model call on a config that cannot be read
  })

  test('Save on that first launch replaces the unreadable config.json', async ({ page, os, world }) => {
    await expect(sourcesHeading(page)).toBeVisible(LAUNCH)
    await pick(page, os, [rawCv(world)])
    await continueButton(page).click()
    await page.getByRole('button', { name: 'Go on without a draft', exact: true }).click()
    await expect(reviewHeading(page)).toBeVisible(LAUNCH)
    await page.getByLabel('Name', { exact: true }).fill('Mette Kjær Larsen')
    await page.getByLabel('Email', { exact: true }).fill('mette.kjaer.larsen@example.com')
    await page.getByLabel('City', { exact: true }).selectOption('Copenhagen')
    await page.getByLabel('Add your own title', { exact: true }).fill('Senior Data Scientist')
    await page.getByLabel('Add your own title', { exact: true }).press('Enter')
    await page.getByRole('button', { name: 'Save and start searching', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Finding jobs', level: 1 })).toBeVisible({ timeout: 20_000 })
    expect(world.readJson('profile/config.json')).not.toHaveProperty('foo')
  })
})
