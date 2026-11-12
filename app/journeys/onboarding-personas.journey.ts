// A first launch, start to finish, for each person of the world: their own messy CV picked from disk,
// read by the stand-in claude, reviewed and saved; the first run starts (search and match only).
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from './fixtures'
import { employerSources, fold, LAUNCH, reason, saveAndSearch, titleBox, toReview } from './helpers/onboarding'
import type { World } from '../test/world/build'
import type { Page } from '@playwright/test'

const finding = (page: Page) => page.getByRole('heading', { name: 'Finding jobs', level: 1 })
const cvOnDisk = (world: World) => readFileSync(join(world.home, 'profile', 'cv.md'), 'utf8')
const checkedLanguages = async (page: Page) => {
  const group = page.getByRole('group', { name: 'Languages of the job ads' })
  const out: string[] = []
  for (const box of await group.getByRole('checkbox').all()) if (await box.isChecked()) out.push((await box.evaluate((b) => b.closest('label')?.textContent ?? '')).trim())
  return out
}

/** Save, then what every first launch ends with: the profile written, the CV written, the first run started. */
async function saveAndCheck(page: Page, world: World, expected: Record<string, unknown>, cv: string) {
  expect(world.exists('profile/config.json')).toBe(false)
  expect(world.toolCalls('init_profile')).toEqual([])
  await saveAndSearch(page).click()
  await expect(finding(page)).toBeVisible(LAUNCH)
  expect(world.readJson('profile/config.json')).toMatchObject(expected)
  expect(cvOnDisk(world)).toBe(cv)
  expect(world.exists('profile/cv.draft.md')).toBe(false)
  await expect.poll(() => world.toolCalls('find_jobs').map((c) => c.args?.skip)).toEqual([['discover', 'follow', 'collect']])
}

test.describe('mette, Copenhagen', () => {
  test.use({ worldOptions: { empty: true, persona: 'mette' } })

  test('mette’s CV fills in everything: a Danish data scientist with LinkedIn offered, unticked', { tag: '@core' }, async ({ page, world, os }) => {
    await toReview(page, world, os)
    await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Mette Kjær Larsen')
    await expect(page.getByLabel('Email', { exact: true })).toHaveValue('mette.kjaer.larsen@example.com')
    await expect(page.getByLabel('City', { exact: true })).toHaveValue('Copenhagen')
    expect(await checkedLanguages(page)).toEqual(['English', 'Danish'])
    await expect(page.getByText(/could not be found in your sources/)).toHaveCount(0)
    await expect(titleBox(page, 'Senior Data Scientist')).toBeChecked()
    expect(await employerSources(page)).toEqual([{ label: 'LinkedIn', on: false }])
    await expect(fold(page, 'CV').locator('summary')).toContainText('Ready')
    await expect(reason(page)).toHaveCount(0)
    await saveAndCheck(
      page,
      world,
      {
        name: 'Mette Kjær Larsen',
        location: 'Copenhagen',
        languages: ['English', 'Danish'],
        role_targets: ['Senior Data Scientist', 'Lead Data Scientist'],
        search_keywords: world.persona.searchKeywords,
        linkedin_discovery: false,
      },
      world.persona.cv,
    )
  })
})

test.describe('lea, Lyon', () => {
  test.use({ worldOptions: { empty: true, persona: 'lea' } })

  test('léa’s French CV: French ads ticked, Lyon’s sources LinkedIn and HelloWork offered, unticked', async ({ page, world, os }) => {
    await toReview(page, world, os)
    await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Léa Moreau')
    await expect(page.getByLabel('Email', { exact: true })).toHaveValue('lea.moreau@example.com')
    await expect(page.getByLabel('City', { exact: true })).toHaveValue('Lyon')
    expect(await checkedLanguages(page)).toEqual(['English', 'French'])
    await expect(titleBox(page, 'Contrôleuse de gestion')).toBeChecked()
    await expect(titleBox(page, 'Contrôleur de gestion industriel')).toBeChecked()
    await expect(titleBox(page, 'Business Controller')).not.toBeChecked()
    expect(await employerSources(page)).toEqual([
      { label: 'LinkedIn', on: false },
      { label: 'HelloWork', on: false },
    ])
    expect(world.toolCalls('keywords').map((c) => c.args?.languages)).toEqual([['English', 'French']])
    await page.getByRole('checkbox', { name: 'HelloWork', exact: true }).check()
    await saveAndCheck(
      page,
      world,
      {
        name: 'Léa Moreau',
        location: 'Lyon',
        languages: ['English', 'French'],
        role_targets: ['Contrôleuse de gestion', 'Contrôleur de gestion industriel'],
        search_keywords: world.persona.searchKeywords,
        topic_terms: world.persona.topicTerms,
        linkedin_discovery: false,
        hellowork_discovery: true,
      },
      world.persona.cv,
    )
  })
})

test.describe('bence, Budapest', () => {
  test.use({ worldOptions: { empty: true, persona: 'bence' } })

  test('bence’s CV: Hungarian ads ticked, Budapest’s sources LinkedIn and profession.hu offered, unticked', async ({ page, world, os }) => {
    await toReview(page, world, os)
    await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Bence Kovács')
    await expect(page.getByLabel('City', { exact: true })).toHaveValue('Budapest')
    expect(await checkedLanguages(page)).toEqual(['English', 'Hungarian'])
    expect(await employerSources(page)).toEqual([
      { label: 'LinkedIn', on: false },
      { label: 'profession.hu', on: false },
    ])
    await expect(titleBox(page, 'Backend Engineer')).toBeChecked()
    await page.getByRole('radio', { name: 'Remote only', exact: true }).check()
    await saveAndCheck(
      page,
      world,
      {
        name: 'Bence Kovács',
        email: 'bence.kovacs@example.com',
        location: 'Budapest',
        languages: ['English', 'Hungarian'],
        remote: 'yes',
        role_targets: ['Backend Engineer', 'Senior Backend Engineer'],
        linkedin_discovery: false,
        profession_discovery: false,
      },
      world.persona.cv,
    )
  })
})

test.describe('jonas, a CV with gaps', () => {
  test.use({ worldOptions: { empty: true, persona: 'jonas' } })

  test('jonas’ CV names no city: the review asks for it, Save waits until Aarhus is chosen', async ({ page, world, os }) => {
    await toReview(page, world, os)
    await expect(page.getByText('These could not be found in your sources: your city. Fill them in below to finish.')).toBeVisible()
    await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Jonas Berg')
    await expect(page.getByLabel('City', { exact: true })).toHaveValue('')
    await expect(saveAndSearch(page)).toBeDisabled()
    await expect(reason(page)).toHaveText('A city is needed.')
    expect(await checkedLanguages(page)).toEqual(['English', 'Danish'])
    // No city yet: only the worldwide source is offered.
    expect(await employerSources(page)).toEqual([{ label: 'LinkedIn', on: false }])
    await page.getByLabel('City', { exact: true }).selectOption('Aarhus')
    await expect(page.getByText(/could not be found in your sources/)).toHaveCount(0)
    expect(await employerSources(page)).toEqual([{ label: 'LinkedIn', on: false }])
    await expect(saveAndSearch(page)).toBeEnabled()
    await saveAndCheck(page, world, { name: 'Jonas Berg', location: 'Aarhus', languages: ['English', 'Danish'], linkedin_discovery: false }, world.persona.cv)
  })

  test('jonas’ CV has three things to fill in: each marker opens the box on its gap, and what is typed there is saved', async ({ page, world, os }) => {
    await toReview(page, world, os)
    const cv = fold(page, 'CV')
    await expect(cv.locator('summary')).toContainText('3 things to fill in')
    await cv.locator('summary').click()
    const marks = cv.getByRole('button', { name: 'to fill in', exact: true })
    await expect(marks).toHaveCount(3)
    await marks.nth(2).click() // "TODO: thesis title"
    const box = page.getByLabel('Your CV', { exact: true })
    await expect(box).toBeFocused()
    await expect(page.getByRole('switch', { name: 'Preview' })).toHaveAttribute('aria-checked', 'false')
    expect(await box.evaluate((b: HTMLTextAreaElement) => b.value.slice(b.selectionStart, b.selectionEnd))).toBe('TODO')
    await page.keyboard.type('Nitrogen removal in a small rural treatment plant')
    await expect(cv.locator('summary')).toContainText('2 things to fill in')
    await page.getByRole('switch', { name: 'Preview' }).click()
    await marks.first().click() // the phone number
    await page.keyboard.type('+45 00 00 00 00')
    await expect(cv.locator('summary')).toContainText('1 thing to fill in')
    await page.getByLabel('City', { exact: true }).selectOption('Aarhus')
    const expected = world.persona.cv
      .replace('**Phone:** TODO', '**Phone:** +45 00 00 00 00')
      .replace('TODO: thesis title', 'Nitrogen removal in a small rural treatment plant: thesis title')
    await saveAndCheck(page, world, { name: 'Jonas Berg', location: 'Aarhus' }, expected)
  })
})
