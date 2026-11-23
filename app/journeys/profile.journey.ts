// Profile → Details: the form of profile/config.json saving itself key by key, the server's refusals
// under their fields, the search terms Claude proposes again on leaving (and the sidebar line when that fails), a config that
// cannot be read and the narrow window. The CV is cv.journey.ts; how the app works (discovery, the Claude folder) is settings.journey.ts.
import { realpathSync } from 'node:fs'
import { expect, test } from './fixtures'
import { addChip, argsOf, config, exists, expectChips, narrow, openDetails, started, writeText } from './helpers/profile'

const leave = (page: import('@playwright/test').Page) => page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Matches', exact: true }).click()
const comeBack = (page: import('@playwright/test').Page) => page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Profile', exact: true }).click()
const STALE = 'Your search terms could not be updated to your new role targets'
const needsYou = (page: import('@playwright/test').Page) => page.getByRole('group', { name: 'Needs you' })

const region = (page: import('@playwright/test').Page, name: string) => page.getByRole('region', { name, exact: true })

test.describe('the Details form', () => {
  test('opens with every section and the saved values', async ({ page, world }) => {
    await openDetails(page)
    for (const name of ['About you', 'What to look for', 'What to skip']) await expect(region(page, name)).toBeVisible()
    await expect(page.getByRole('region', { name: 'In profile/config.json only' })).toHaveCount(0)

    await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Mette Kjær Larsen')
    await expect(page.getByLabel('Email', { exact: true })).toHaveValue('mette.kjaer.larsen@example.com')
    await expect(page.getByRole('combobox', { name: 'City' })).toHaveValue('Copenhagen')
    await expect(page.getByRole('radio', { name: 'Hybrid' })).toBeChecked()
    await expect(page.getByRole('radio', { name: 'Remote only' })).not.toBeChecked()
    const langs = page.getByRole('group', { name: 'Languages of the job ads' })
    await expect(langs.getByRole('checkbox', { name: 'English' })).toBeChecked()
    await expect(langs.getByRole('checkbox', { name: 'Danish' })).toBeChecked()
    await expect(langs.getByRole('checkbox', { name: 'French' })).not.toBeChecked()
    await expectChips(page, 'Role targets', world.persona.roleTargets)
    await expect(page.getByRole('radio', { name: 'Balanced' })).toBeChecked()
    await expect(page.getByRole('checkbox', { name: 'I need a visa or work permit' })).not.toBeChecked()
    await expectChips(page, 'Words that rule an ad out', ['internship', 'unpaid'])
    await expectChips(page, 'Companies to skip', [])
    // how the app works is in Settings, not here
    await expect(page.getByRole('checkbox', { name: 'LinkedIn' })).toHaveCount(0)
    await expect(page.getByLabel('Claude config folder', { exact: true })).toHaveCount(0)
    // nothing to press: the details save themselves
    await expect(page.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Undo changes' })).toHaveCount(0)
    // the sections aside
    const sections = page.getByRole('navigation', { name: 'Sections' })
    await expect(sections.getByRole('link')).toHaveText(['About you', 'What to look for', 'What to skip', 'Master CV', 'CV style', 'Stories'])
  })

  test('each edit is written on its own, with nothing to press, and is there when you come back', { tag: '@core' }, async ({ page, world }) => {
    const before = config(world)
    await openDetails(page)
    await page.getByLabel('Name', { exact: true }).fill('Mette K. Larsen')
    await page.getByLabel('Email', { exact: true }).fill('mette@example.org')
    await page.getByRole('checkbox', { name: 'I need a visa or work permit' }).check()
    await page.getByRole('radio', { name: 'Strong' }).check()
    await expect.poll(() => config(world).min_score).toBe(0.75)
    await expect.poll(() => config(world).email, { timeout: 10_000 }).toBe('mette@example.org')
    expect(config(world)).toEqual({
      ...before,
      name: 'Mette K. Larsen',
      email: 'mette@example.org',
      min_score: 0.75,
      needs_work_permit: true,
    })
    await expect(page.getByText(/unsaved/)).toHaveCount(0)
    await leave(page)
    await comeBack(page)
    await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Mette K. Larsen')
    await expect(page.getByRole('radio', { name: 'Strong' })).toBeChecked()
    // a name alone asks Claude nothing
    expect(world.claudeCalls('keywords')).toHaveLength(0)
  })

  test('a city typed after Other… is kept', async ({ page, world }) => {
    await openDetails(page)
    const city = page.getByRole('combobox', { name: 'City' })
    await city.selectOption('Other…')
    await page.getByRole('textbox', { name: 'Your city' }).fill('Reykjavik')
    await page.getByRole('textbox', { name: 'Your city' }).blur()
    await expect.poll(() => config(world).location).toBe('Reykjavik')
  })
})

test.describe('the server refuses a value', () => {
  test('a refusal is said under its field, and the last good value stays on disk', async ({ page, world }) => {
    await openDetails(page)
    for (const role of world.persona.roleTargets) await page.getByRole('button', { name: `Remove ${role}`, exact: true }).click()
    await expect(page.getByText('role_targets must contain at least one entry')).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0) // under the fields, none above the form
    // each removal before the last was fine and is written; the one that would leave none was refused
    expect(config(world).role_targets).toEqual(world.persona.roleTargets.slice(-1))
  })

  test('a failing write says why above the form; the next edit goes through', async ({ page, world }) => {
    await openDetails(page)
    world.faults({ tools: { init_profile: { error: 'profile/config.json is being written by another program' } } })
    await page.getByLabel('Name', { exact: true }).fill('Mette K. Larsen')
    await page.getByLabel('Name', { exact: true }).blur()
    await expect(page.getByRole('alert')).toHaveText('profile/config.json is being written by another program')
    await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Mette K. Larsen')
    expect(config(world).name).toBe('Mette Kjær Larsen')
    world.clearFaults()
    await page.getByLabel('Name', { exact: true }).fill('Mette K. Larsen!')
    await page.getByLabel('Name', { exact: true }).blur()
    await expect.poll(() => config(world).name).toBe('Mette K. Larsen!')
    await expect(page.getByRole('alert')).toHaveCount(0)
  })
})

test.describe('the search terms', () => {
  const proposal = { keywords: ['data scientist', 'ml engineer', 'dataforsker'], topic_terms: ['data scien*', 'energy'] }

  test('a change of role targets has Claude propose the search terms again on leaving', async ({ page, world }) => {
    await openDetails(page)
    world.faults({ claude: { keywords: { answer: proposal } } })
    await addChip(page, 'Role targets', 'Energy Analyst')
    await expect.poll(() => config(world).role_targets).toContain('Energy Analyst')
    expect(world.claudeCalls('keywords')).toHaveLength(0) // not while still on Profile
    await leave(page)
    await expect.poll(() => config(world).search_keywords, { timeout: 30_000 }).toEqual(proposal.keywords)
    expect(argsOf(world, 'keywords')).toEqual([{ save: true }])
    expect(config(world)).toMatchObject({ topic_terms: proposal.topic_terms })
    await expect(needsYou(page).getByRole('button', { name: STALE })).toHaveCount(0)
  })

  test('a proposal that fails leaves a line that opens What to look for; the next one clears it', async ({ page, world }) => {
    await openDetails(page)
    world.faults({ claude: { keywords: { fail: 'Claude usage limit reached' } } })
    await addChip(page, 'Role targets', 'Energy Analyst')
    await expect.poll(() => config(world).role_targets).toContain('Energy Analyst')
    await leave(page)
    const line = needsYou(page).getByRole('button', { name: STALE })
    await expect(line).toBeVisible({ timeout: 30_000 })
    await line.click()
    await expect(page.getByRole('heading', { name: 'What to look for', level: 2 })).toBeInViewport()
    world.faults({ claude: { keywords: { answer: proposal } } })
    await addChip(page, 'Role targets', 'Grid Analyst')
    await expect.poll(() => config(world).role_targets).toContain('Grid Analyst')
    await leave(page)
    await expect(needsYou(page).getByRole('button', { name: STALE })).toHaveCount(0, { timeout: 30_000 })
    expect(config(world).search_keywords).toEqual(proposal.keywords)
  })
})

test.describe('a profile with no CV', () => {
  test.use({ worldOptions: { noCv: true } })

  test('editing the details does not make up a CV', async ({ page, world }) => {
    await openDetails(page)
    await page.getByLabel('Name', { exact: true }).fill('Mette K. Larsen')
    await page.getByLabel('Name', { exact: true }).blur()
    await expect.poll(() => config(world).name).toBe('Mette K. Larsen')
    expect(exists(world, 'profile/cv.md')).toBe(false)
  })
})

test.describe('Details cannot be read', () => {
  test('a broken config.json lists what is wrong, with the file and the key', async ({ page, world }) => {
    await started(page)
    writeText(world, 'profile/config.json', JSON.stringify({ ...config(world), remote: 'sometimes', colour: 'blue' }, null, 2))
    await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Profile', exact: true }).click()
    const alert = page.getByRole('alert')
    await expect(alert).toContainText('profile/config.json could not be read:')
    const home = realpathSync(world.home)
    await expect(alert.getByRole('listitem')).toHaveText([
      `${home}/profile/config.json: remote — Input should be 'yes', 'no' or 'hybrid'`,
      `${home}/profile/config.json: colour — Extra inputs are not permitted`,
    ])
    await expect(page.getByRole('region', { name: 'About you' })).toHaveCount(0)
  })

  test('a part that could not be read says so, and the rest of the page is there', async ({ page, world }) => {
    await started(page)
    world.faults({ tools: { show_profile: { error: 'profile/ is not readable', once: true } } })
    await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Profile', exact: true }).click()
    await expect(page.getByRole('alert')).toHaveText('profile/ is not readable')
    await expect(page.getByRole('region', { name: 'Stories' })).toBeVisible()
  })
})

test.describe('a narrow window', () => {
  test('has no sections aside; the form saves itself the same', async ({ app, page, world }) => {
    await started(page)
    await narrow(app)
    await openDetails(page)
    await expect(page.getByRole('navigation', { name: 'Sections' })).toHaveCount(0)
    await expect(page.getByRole('group', { name: 'Needs you' })).toBeHidden()
    await page.getByLabel('Name', { exact: true }).fill('Mette K. Larsen')
    await page.getByLabel('Name', { exact: true }).blur()
    await expect.poll(() => config(world).name).toBe('Mette K. Larsen')
  })
})
