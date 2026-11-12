// Settings in the built app with a real door server: a line at the sidebar's foot says the (stand-in)
// claude is not signed in, Settings' Claude row signs in through the app's own sign-in, and the line goes.
// Google Drive is only looked at: Connect would open a real browser, so it is never clicked.
import { existsSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { _electron as electron, expect, test } from '@playwright/test'
import { buildHome } from '../test/home-fixture'

const APP = resolve(__dirname, '..')
const fixture = buildHome()

test.skip(!fixture.hasPython, `no Python at ${fixture.python} (set DOOR_PYTHON)`)

test('the sidebar line opens Settings, where Claude is signed in from its row', async () => {
  const app = await electron.launch({
    args: ['.', ...(process.env.CI ? ['--no-sandbox'] : [])],
    cwd: APP,
    env: { ...(process.env as Record<string, string>), ...fixture.env },
  })
  try {
    const page = await app.firstWindow()
    await page.getByRole('complementary').getByRole('button', { name: 'Claude is not signed in' }).click({ timeout: 60_000 })
    const claude = page.getByRole('listitem', { name: 'Claude', exact: true })
    const drive = page.getByRole('listitem', { name: 'Google Drive', exact: true })
    await expect(claude).toContainText('Not signed in')
    await expect(drive).toContainText('Keeps this computer and another one in step.')
    await expect(drive.getByRole('button', { name: 'Connect' })).toBeVisible()
    await expect(page.getByRole('region', { name: 'Your data' })).toContainText(fixture.home)

    await claude.getByRole('button', { name: 'Sign in with Claude' }).click()
    await claude.getByRole('button', { name: 'The page showed a code?' }).click()
    await claude.getByLabel('Sign-in code').fill('stand-in-code#ok')
    await claude.getByRole('button', { name: 'Send code' }).click()
    await expect(claude).toContainText('Signed in as ada@example.com (Max)', { timeout: 30_000 })
    await expect(page.getByRole('complementary').getByRole('button', { name: 'Claude is not signed in' })).toHaveCount(0)
    // the profile's email was filled in on claude's page
    expect(readFileSync(join(fixture.scratch, 'claude-login-args'), 'utf8')).toContain('--email')
    expect(existsSync(join(fixture.scratch, 'claude-was-called'))).toBe(false)
  } finally {
    await app.close()
  }
})
