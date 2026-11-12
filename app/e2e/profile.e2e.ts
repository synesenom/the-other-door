// Profile in the built app with a real door server: a value init_profile refuses is explained under its
// field and nothing is written; a valid change is written to the temp home's config.json and nothing else is.
import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { _electron as electron, expect, test } from '@playwright/test'
import { buildHome } from '../test/home-fixture'

const APP = resolve(__dirname, '..')
const fixture = buildHome()

test.skip(!fixture.hasPython, `no Python at ${fixture.python} (set DOOR_PYTHON)`)

test('edits the profile: an invalid value is explained in place, a valid one is saved', async () => {
  const configPath = join(fixture.home, 'profile', 'config.json')
  const before = JSON.parse(readFileSync(configPath, 'utf8'))
  const app = await electron.launch({
    args: ['.', ...(process.env.CI ? ['--no-sandbox'] : [])],
    cwd: APP,
    env: { ...(process.env as Record<string, string>), ...fixture.env },
  })
  try {
    const page = await app.firstWindow()
    await page.getByRole('button', { name: 'Profile', exact: true }).click({ timeout: 60_000 })
    const roles = page.getByRole('list', { name: 'Role targets, chosen' }).getByRole('button')
    await expect(roles.first()).toBeVisible({ timeout: 30_000 })
    while (await roles.count()) await roles.first().click()
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('role_targets must contain at least one entry')).toBeVisible({ timeout: 30_000 })
    expect(JSON.parse(readFileSync(configPath, 'utf8'))).toEqual(before)

    await page.getByRole('button', { name: 'Undo changes' }).click()
    await page.getByRole('radio', { name: 'Strong' }).check()
    await page.getByRole('checkbox', { name: 'I need a visa or work permit' }).check()
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('Saved.')).toBeVisible({ timeout: 30_000 })
    const after = JSON.parse(readFileSync(configPath, 'utf8'))
    expect(after).toEqual({ ...before, min_score: 0.75, needs_work_permit: true })
  } finally {
    await app.close()
  }
})
