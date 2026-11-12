// A new computer for someone who already uses The other door: the first screen offers their profile on Google Drive
// (the world's `drive/` folder plays the account). A pull lands on Matches with their own profile and no run; an empty Drive
// says so and leaves the normal onboarding.
import { existsSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { buildWorld } from '../test/world/build'
import { expect } from './fixtures'
import { LAUNCH, sourcesHeading } from './helpers/onboarding'
import { before, driveArchive, driveState, exportHome, test } from './helpers/settings'
import type { Page } from '@playwright/test'

const fromDrive = (page: Page) => page.getByRole('button', { name: 'Bring my profile from Google Drive', exact: true })

test.describe('an empty home, Drive holds a profile', () => {
  test.use({
    worldOptions: { empty: true },
    // another computer's data: a second world, exported into this one's Drive
    seed: before((world) => {
      const other = buildWorld({ persona: 'mette' })
      mkdirSync(join(world.dir, 'drive'), { recursive: true })
      exportHome(other, driveArchive(world))
    }),
  })

  test('Bring my profile from Google Drive lands on Matches with the pulled profile: no review, no run', async ({ page, world }) => {
    await expect(sourcesHeading(page)).toBeVisible(LAUNCH)
    await fromDrive(page).click()
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible(LAUNCH)
    expect(world.exists('profile/config.json')).toBe(true)
    expect(existsSync(driveState(world))).toBe(true) // Drive stays connected
    expect(world.toolCalls('find_jobs')).toEqual([])
    expect(world.toolCalls('init_profile')).toEqual([])
  })
})

test.describe('an empty home, an empty Drive', () => {
  test.use({ worldOptions: { empty: true } })

  test('says Drive has nothing yet and the onboarding goes on', async ({ page, world }) => {
    await expect(sourcesHeading(page)).toBeVisible(LAUNCH)
    await fromDrive(page).click()
    await expect(page.getByRole('status')).toContainText('There is nothing from The other door on your Google Drive yet')
    await expect(sourcesHeading(page)).toBeVisible()
    expect(world.exists('profile/config.json')).toBe(false)
  })
})

test.describe('Drive is not configured in this build', () => {
  test.use({ worldOptions: { empty: true, drive: { configured: false } } })

  test('says why, and the onboarding is still there', async ({ page }) => {
    await expect(sourcesHeading(page)).toBeVisible(LAUNCH)
    await fromDrive(page).click()
    await expect(page.getByRole('alert')).toContainText('not configured in this build')
    await expect(sourcesHeading(page)).toBeVisible()
  })
})
