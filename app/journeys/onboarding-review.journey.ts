// The wizard's review, "Check your answers": answers edited in place, new titles proposing new search
// terms, the CV, the employer sources, and Save's failures (tool faults). Nothing is written before Save.
import { readFileSync } from 'node:fs'
import { expect, test } from './fixtures'
import {
  fold,
  LAUNCH,
  reason,
  reviewHeading,
  saveAndSearch,
  titleBox,
  toReview,
} from './helpers/onboarding'
import type { Page } from '@playwright/test'

test.use({ worldOptions: { empty: true } })

const finding = (page: Page) => page.getByRole('heading', { name: 'Finding jobs', level: 1 })
const name = (page: Page) => page.getByLabel('Name', { exact: true })
const email = (page: Page) => page.getByLabel('Email', { exact: true })
const city = (page: Page) => page.getByLabel('City', { exact: true })
const lang = (page: Page, l: string) => page.getByRole('checkbox', { name: l, exact: true })

/** Nothing on disk but the scratch draft, and no write called, until Save. */
function nothingSaved(world: import('../test/world/build').World) {
  expect(world.exists('profile/config.json')).toBe(false)
  expect(world.exists('profile/cv.md')).toBe(false)
  expect(world.toolCalls('init_profile')).toEqual([])
  expect(world.toolCalls('save_cv')).toEqual([])
}

test('You: name, email, city, where to work and the ad languages are all changed in place and saved as changed', async ({ page, world, os }) => {
  await toReview(page, world, os)
  await name(page).fill('Mette K. Larsen')
  await email(page).fill('mette@larsen.example.com')
  await city(page).selectOption('Odense')
  await page.getByRole('radio', { name: 'On site', exact: true }).check()
  await lang(page, 'Danish').uncheck()
  await lang(page, 'Swedish').check()
  nothingSaved(world)
  await saveAndSearch(page).click()
  await expect(finding(page)).toBeVisible(LAUNCH)
  expect(world.readJson('profile/config.json')).toMatchObject({
    name: 'Mette K. Larsen',
    email: 'mette@larsen.example.com',
    location: 'Odense',
    remote: 'no',
    languages: ['English', 'Swedish'],
  })
})

test('with every title unticked, Save says a title is needed', async ({ page, world, os }) => {
  await toReview(page, world, os)
  await titleBox(page, 'Senior Data Scientist').uncheck()
  await titleBox(page, 'Lead Data Scientist').uncheck()
  await expect(saveAndSearch(page)).toBeDisabled()
  await expect(reason(page)).toHaveText('Choose at least one title.', { timeout: 5_000 })
})

test('titles: the recommended ones start ticked; unticking one and ticking another proposes new search terms, Save waiting meanwhile', async ({ page, world, os }) => {
  await toReview(page, world, os)
  await expect(titleBox(page, 'Senior Data Scientist')).toBeChecked()
  await expect(titleBox(page, 'Lead Data Scientist')).toBeChecked()
  await expect(titleBox(page, 'Machine Learning Engineer')).not.toBeChecked()
  await expect(titleBox(page, 'Forecasting Specialist')).not.toBeChecked()
  await expect(page.getByRole('group', { name: 'The job titles to look for' }).getByRole('checkbox', { name: 'Senior Data Scientist your latest title' })).toBeVisible()
  expect(world.toolCalls('keywords')).toHaveLength(1)

  world.faults({ tools: { keywords: { delay_s: 2 } } })
  await titleBox(page, 'Lead Data Scientist').uncheck()
  await titleBox(page, 'Forecasting Specialist').check()
  await expect(reason(page)).toHaveText('Choosing search terms for your titles…')
  await expect(fold(page, 'Search').locator('summary')).toContainText('Choosing them…')
  await expect(saveAndSearch(page)).toBeDisabled()
  await expect(saveAndSearch(page)).toBeEnabled(LAUNCH)
  expect(world.toolCalls('keywords').map((c) => c.args?.role_targets)).toEqual([
    ['Senior Data Scientist', 'Lead Data Scientist'],
    ['Senior Data Scientist', 'Forecasting Specialist'],
  ])
  world.clearFaults()
  await saveAndSearch(page).click()
  await expect(finding(page)).toBeVisible(LAUNCH)
  expect(world.readJson('profile/config.json').role_targets).toEqual(['Senior Data Scientist', 'Forecasting Specialist'])
})

test('CV: the draft is shown formatted, edited in the box, and the edited text is what cv.md holds', async ({ page, world, os }) => {
  await toReview(page, world, os)
  const cv = fold(page, 'CV')
  await expect(cv).not.toHaveAttribute('open') // a draft was made: folded
  await expect(cv.locator('summary')).toContainText('Ready')
  await cv.locator('summary').click()
  await expect(page.getByRole('switch', { name: 'Preview' })).toHaveAttribute('aria-checked', 'true')
  await expect(cv.getByRole('heading', { name: 'Mette Kjær Larsen' })).toBeVisible()
  await page.getByRole('switch', { name: 'Preview' }).click()
  const box = page.getByLabel('Your CV', { exact: true })
  await expect(box).toHaveValue(world.persona.cv)
  const edited = world.persona.cv.replace('Senior data scientist with nine years', 'Senior data scientist with ten years')
  await box.fill(edited)
  nothingSaved(world)
  await saveAndSearch(page).click()
  await expect(finding(page)).toBeVisible(LAUNCH)
  expect(world.readJson('profile/config.json').name).toBe('Mette Kjær Larsen')
  expect(readFileSync(`${world.home}/profile/cv.md`, 'utf8')).toBe(edited)
  expect(world.exists('profile/cv.draft.md')).toBe(false) // the scratch draft is gone
  expect(world.toolCalls('save_cv').map((c) => c.args?.markdown)).toEqual([edited])
})

test('Where to find employers: Copenhagen offers LinkedIn, unticked; ticking it saves it on', async ({ page, world, os }) => {
  await toReview(page, world, os)
  const group = page.getByRole('group', { name: 'Find employers on' })
  await expect(group.getByRole('checkbox')).toHaveCount(1)
  await expect(page.getByRole('checkbox', { name: 'LinkedIn', exact: true })).not.toBeChecked()
  await page.getByRole('checkbox', { name: 'LinkedIn', exact: true }).check()
  // The list follows the city.
  await city(page).selectOption('Lyon')
  await expect(page.getByRole('checkbox', { name: 'HelloWork', exact: true })).toBeVisible()
  await city(page).selectOption('Copenhagen')
  await expect(page.getByRole('checkbox', { name: 'HelloWork', exact: true })).toHaveCount(0)
  await saveAndSearch(page).click()
  await expect(finding(page)).toBeVisible(LAUNCH)
  const config = world.readJson('profile/config.json')
  expect(config.linkedin_discovery).toBe(true)
  expect(config).not.toHaveProperty('hellowork_discovery')
})

test('Save writes config.json and cv.md with exactly the reviewed answers, then the first run starts with only search and match', async ({ page, world, os }) => {
  await toReview(page, world, os)
  nothingSaved(world)
  await saveAndSearch(page).click()
  await expect(finding(page)).toBeVisible(LAUNCH)
  const config = world.readJson('profile/config.json')
  expect(config).toMatchObject({
    name: 'Mette Kjær Larsen',
    email: 'mette.kjaer.larsen@example.com',
    location: 'Copenhagen',
    languages: ['English', 'Danish'],
    role_targets: ['Senior Data Scientist', 'Lead Data Scientist'],
    search_keywords: world.persona.searchKeywords,
    topic_terms: world.persona.topicTerms,
    remote: 'hybrid',
    exclude: { companies: [], keywords: [] },
    linkedin_discovery: false,
  })
  expect(config.enrich_sources).toEqual([]) // no page was given
  expect(readFileSync(`${world.home}/profile/cv.md`, 'utf8')).toBe(world.persona.cv)
  expect(world.toolCalls('init_profile')).toHaveLength(1)
  expect(world.toolCalls('save_cv')).toHaveLength(1)
  await expect.poll(() => world.toolCalls('find_jobs').map((c) => c.args?.skip)).toEqual([['discover', 'follow', 'collect']])
})

test('init_profile refusing a field puts its message under the part that owns it; the next Save goes through', async ({ page, world, os }) => {
  await toReview(page, world, os)
  world.faults({
    tools: {
      init_profile: {
        error: 'profile/config.json: search_keywords — at most 40 search terms\nprofile/config.json: min_score — min_score must be between 0.0 and 1.0\nsomething else went wrong',
        once: true,
      },
    },
  })
  await saveAndSearch(page).click()
  const search = fold(page, 'Search')
  await expect(search).toHaveAttribute('open', '') // opened to show it
  await expect(search.getByRole('alert')).toHaveText('at most 40 search terms')
  await expect(page.getByRole('region', { name: 'Check your answers', exact: true }).getByRole('alert').first().getByRole('listitem')).toHaveText(['min_score: min_score must be between 0.0 and 1.0', 'something else went wrong'])
  await expect(reviewHeading(page)).toBeVisible()
  expect(world.exists('profile/config.json')).toBe(false)
  expect(world.toolCalls('save_cv')).toEqual([])
  await reviewHeading(page).scrollIntoViewIfNeeded()
  // Editing the Search part clears its message; the top list stays until the next Save.
  await page.getByRole('textbox', { name: 'Search terms', exact: true }).fill('energy analyst')
  await page.getByRole('textbox', { name: 'Search terms', exact: true }).press('Enter')
  await expect(search.getByRole('alert')).toHaveCount(0)
  await saveAndSearch(page).click()
  await expect(finding(page)).toBeVisible(LAUNCH)
  expect(world.toolCalls('init_profile')).toHaveLength(2)
})

test('a CV that could not be saved says the answers are saved but the CV is not; Save again saves it and starts the run', async ({ page, world, os }) => {
  await toReview(page, world, os)
  world.faults({ tools: { save_cv: { error: "[Errno 28] No space left on device: 'profile/cv.md'", once: true } } })
  await saveAndSearch(page).click()
  await expect(page.getByRole('alert')).toHaveText("Your answers are saved, but the CV was not: [Errno 28] No space left on device: 'profile/cv.md'")
  await expect(reviewHeading(page)).toBeVisible()
  expect(world.exists('profile/config.json')).toBe(true)
  expect(world.exists('profile/cv.md')).toBe(false) // init_profile no longer copies the example CV
  expect(world.toolCalls('find_jobs')).toEqual([])
  await saveAndSearch(page).click()
  await expect(finding(page)).toBeVisible(LAUNCH)
  expect(readFileSync(`${world.home}/profile/cv.md`, 'utf8')).toBe(world.persona.cv)
})

test('a failed read-back after a good Save is not reported as an unsaved CV', async ({ page, world, os }) => {
  await toReview(page, world, os)
  const reads = world.toolCalls('show_profile').length
  world.faults({ tools: { show_profile: { error: 'The other door took too long to answer', once: true } } })
  await saveAndSearch(page).click()
  await expect.poll(() => world.toolCalls('show_profile').length).toBeGreaterThan(reads)
  await expect(page.getByRole('status').filter({ hasText: 'Saving…' })).toHaveCount(0)
  expect(world.toolCalls('save_cv')).toHaveLength(1) // the CV was saved
  await expect(page.getByText(/the CV was not/)).toHaveCount(0)
})

test.describe('the example story', () => {
  const story = (page: Page) => page.getByRole('region', { name: 'Your story bank' })
  const drafted = {
    title: 'Built the forecasting models', context: 'The team planned with spreadsheets.', action: 'Built the models in Python.',
    result: 'The planners used them every week.', learning: '', missing: ['learning'], conflicts: [],
  }

  test('shows one story from the CV; Save waits for its empty part, then puts it in the story bank', async ({ page, world, os }) => {
    world.faults({ claude: { stories: { answer: { stories: [drafted] } } } })
    await toReview(page, world, os)
    await expect(story(page).getByText(/A story tells what was behind it/)).toBeVisible()
    await expect(story(page).getByRole('checkbox', { name: 'Keep this story' })).toBeChecked()
    await expect(saveAndSearch(page)).toBeDisabled()
    await expect(reason(page)).toHaveText('Fill in the Learning of your story, or untick it.', { timeout: 5_000 })
    expect(world.exists('profile/story_bank.md')).toBe(false)
    await story(page).getByLabel('Learning', { exact: true }).fill('A forecast is used once people can check it.')
    await saveAndSearch(page).click()
    await expect(finding(page)).toBeVisible(LAUNCH)
    const bank = readFileSync(`${world.home}/profile/story_bank.md`, 'utf8')
    expect(bank).toContain('Built the forecasting models')
    expect(bank).toContain('A forecast is used once people can check it.')
  })

  test('unticked, nothing goes in the story bank', async ({ page, world, os }) => {
    world.faults({ claude: { stories: { answer: { stories: [drafted] } } } })
    await toReview(page, world, os)
    await story(page).getByRole('checkbox', { name: 'Keep this story' }).uncheck()
    await saveAndSearch(page).click()
    await expect(finding(page)).toBeVisible(LAUNCH)
    expect(world.exists('profile/story_bank.md')).toBe(false)
  })

  test('a story Claude could not draft is said nowhere: the review has no story part', async ({ page, world, os }) => {
    world.faults({ claude: { stories: { fail: 'claude timed out' } } })
    await toReview(page, world, os)
    await expect(story(page)).toHaveCount(0)
    await expect(saveAndSearch(page)).toBeEnabled()
  })
})
