// Profile → Details: the form of profile/config.json, Save writing exactly what changed, the server's
// refusals under their fields, Undo after Other…, the search terms Claude keeps up to date, a config that cannot be read and the
// narrow window. The CV is cv.journey.ts; how the app works (discovery, the Claude folder) is settings.journey.ts.
import { realpathSync } from 'node:fs'
import { expect, test } from './fixtures'
import { addChip, argsOf, config, exists, expectChips, narrow, openDetails, saveButton, started, writeText } from './helpers/profile'

const region = (page: import('@playwright/test').Page, name: string) => page.getByRole('region', { name, exact: true })

test.describe('the Details form', () => {
  test('opens on Details with every section and the saved values', async ({ page, world }) => {
    await openDetails(page)
    const parts = page.getByRole('group', { name: 'Part of the profile' })
    await expect(parts.getByRole('button', { name: 'Details', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await expect(parts.getByRole('button', { name: 'CV', exact: true })).toHaveAttribute('aria-pressed', 'false')
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
    // the save bar: nothing to save yet
    await expect(saveButton(page)).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Undo changes' })).toBeDisabled()
    // the sections aside
    const sections = page.getByRole('navigation', { name: 'Sections' })
    await expect(sections.getByRole('link')).toHaveText(['About you', 'What to look for', 'What to skip', 'CV', 'Stories'])
  })

  test('Save writes the changed text, flag and number fields and nothing else', { tag: '@core' }, async ({ page, world }) => {
    const before = config(world)
    await openDetails(page)
    await page.getByLabel('Name', { exact: true }).fill('Mette K. Larsen')
    await page.getByLabel('Email', { exact: true }).fill('mette@example.org')
    await page.getByRole('checkbox', { name: 'I need a visa or work permit' }).check()
    await page.getByRole('radio', { name: 'Strong' }).check()
    await expect(page.getByText('4 unsaved changes')).toBeVisible()
    await saveButton(page).click()
    await expect(page.getByText('Saved.', { exact: true })).toBeVisible()
    await expect(saveButton(page)).toBeDisabled()
    expect(config(world)).toEqual({
      ...before,
      name: 'Mette K. Larsen',
      email: 'mette@example.org',
      min_score: 0.75,
      needs_work_permit: true,
    })
    expect(argsOf(world, 'init_profile')).toEqual([
      {
        name: 'Mette K. Larsen',
        email: 'mette@example.org',
        min_score: 0.75,
        other: { needs_work_permit: true },
      },
    ])
    // the form shows what was saved; the next edit clears "Saved."
    await expect(page.getByRole('radio', { name: 'Strong' })).toBeChecked()
    await page.getByLabel('Name', { exact: true }).fill('Mette')
    await expect(page.getByText('Saved.', { exact: true })).toHaveCount(0)
    await expect(page.getByText('1 unsaved change', { exact: true })).toBeVisible()
  })
})

test.describe('Undo changes', () => {

  test('puts the city back after Other…', async ({ page }) => {
    await openDetails(page)
    const city = page.getByRole('combobox', { name: 'City' })
    await city.selectOption('Other…')
    await page.getByRole('textbox', { name: 'Your city' }).fill('Reykjavik')
    await page.getByRole('button', { name: 'Undo changes' }).click()
    await expect(page.getByRole('textbox', { name: 'Your city' })).toHaveCount(0, { timeout: 3_000 })
    await expect(city).toHaveValue('Copenhagen', { timeout: 3_000 })
  })
})

test.describe('the server refuses a value', () => {
  test('each refusal is said under its field, and nothing is written', async ({ page, world }) => {
    const before = readTextConfig(world)
    await openDetails(page)
    for (const role of world.persona.roleTargets) await page.getByRole('button', { name: `Remove ${role}`, exact: true }).click()
    await saveButton(page).click()
    await expect(page.getByText('role_targets must contain at least one entry')).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0) // under the fields, none above the form
    await expect(page.getByText('Saved.', { exact: true })).toHaveCount(0)
    expect(readTextConfig(world)).toBe(before)
  })

  test('a failing save says why above the form; the next one goes through', async ({ page, world }) => {
    await openDetails(page)
    world.faults({ tools: { init_profile: { error: 'profile/config.json is being written by another program' } } })
    await page.getByLabel('Name', { exact: true }).fill('Mette K. Larsen')
    await saveButton(page).click()
    await expect(page.getByRole('alert')).toHaveText('profile/config.json is being written by another program')
    await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Mette K. Larsen')
    expect(config(world).name).toBe('Mette Kjær Larsen')
    world.clearFaults()
    await saveButton(page).click()
    await expect(page.getByText('Saved.', { exact: true })).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
    expect(config(world).name).toBe('Mette K. Larsen')
  })
})

test.describe('the search terms', () => {
  const proposal = { keywords: ['data scientist', 'ml engineer', 'dataforsker'], topic_terms: ['data scien*', 'energy'] }

  test('a change of role targets has Claude propose the search terms again on Save', async ({ page, world }) => {
    await openDetails(page)
    world.faults({ claude: { keywords: { answer: proposal } } })
    await addChip(page, 'Role targets', 'Energy Analyst')
    await saveButton(page).click()
    await expect(page.getByText('Saved.', { exact: true })).toBeVisible()
    expect(argsOf(world, 'keywords')).toEqual([{ role_targets: [...world.persona.roleTargets, 'Energy Analyst'], languages: ['English', 'Danish'], save: true }])
    expect(config(world)).toMatchObject({ search_keywords: proposal.keywords, topic_terms: proposal.topic_terms })
  })

  test('a save that leaves the role targets and languages alone asks Claude nothing', async ({ page, world }) => {
    await openDetails(page)
    await page.getByLabel('Name', { exact: true }).fill('Mette')
    await saveButton(page).click()
    await expect(page.getByText('Saved.', { exact: true })).toBeVisible()
    expect(world.claudeCalls('keywords')).toHaveLength(0)
  })
})

test.describe('a profile with no CV', () => {
  test.use({ worldOptions: { noCv: true } })

  test('saving the details does not make up a CV', async ({ page, world }) => {
    await openDetails(page)
    await page.getByLabel('Name', { exact: true }).fill('Mette K. Larsen')
    await saveButton(page).click()
    await expect(page.getByText('Saved.', { exact: true })).toBeVisible()
    expect(config(world).name).toBe('Mette K. Larsen')
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

  test('the CV can still be reached when the details cannot be read', async ({ page, world }) => {
    await started(page)
    world.faults({ tools: { show_profile: { error: 'profile/ is not readable', once: true } } })
    await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Profile', exact: true }).click()
    await expect(page.getByRole('alert')).toHaveText('profile/ is not readable')
    await page.getByRole('group', { name: 'Part of the profile' }).getByRole('button', { name: 'CV', exact: true }).click({ timeout: 3_000 })
    await expect(page.getByRole('textbox', { name: 'Your CV (Markdown)' })).toBeVisible()
  })
})

test.describe('a narrow window', () => {
  test('has no sections aside; the form and its save bar work the same', async ({ app, page, world }) => {
    await started(page)
    await narrow(app)
    await openDetails(page)
    await expect(page.getByRole('navigation', { name: 'Sections' })).toHaveCount(0)
    await expect(page.getByRole('group', { name: 'Needs you' })).toBeHidden()
    await page.getByLabel('Name', { exact: true }).fill('Mette K. Larsen')
    await saveButton(page).click()
    await expect(page.getByText('Saved.', { exact: true })).toBeVisible()
    expect(config(world).name).toBe('Mette K. Larsen')
  })
})

function readTextConfig(world: import('../test/world/build').World): string {
  return JSON.stringify(config(world))
}
