// The wizard's first step, only when Claude is signed out or missing: Connect Claude.
// The stand-in claude (test/world/claude.py) signs in with the code `world-code#ok`; a `noClaude` world
// has no claude at all. The real installer is never run: `setup` answers from a tool fault.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from './fixtures'
import { connectHeading, LAUNCH, sourcesHeading } from './helpers/onboarding'
import type { Page } from '@playwright/test'

const signInButton = (page: Page) => page.getByRole('button', { name: 'Sign in with Claude', exact: true })
const tryAgain = (page: Page) => page.getByRole('button', { name: 'Try again', exact: true })
const checkAgain = (page: Page) => page.getByRole('button', { name: 'Check again', exact: true })
const codeBox = (page: Page) => page.getByLabel('Sign-in code', { exact: true })
const sendCode = (page: Page) => page.getByRole('button', { name: 'Send code', exact: true })
const progress = (page: Page) => page.getByRole('list', { name: 'Progress', exact: true })
const current = (page: Page) => progress(page).locator('[aria-current="step"]')

async function startSignIn(page: Page) {
  await signInButton(page).click()
  await expect(page.getByRole('status').filter({ hasText: 'Finish signing in in your browser. The other door waits here.' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Open the sign-in page again', exact: true })).toBeEnabled()
}

async function typeCode(page: Page, code: string) {
  await page.getByRole('button', { name: 'The page showed a code?', exact: true }).click()
  await codeBox(page).fill(code)
  await sendCode(page).click()
}

test.describe('signed out', () => {
  test.use({ worldOptions: { empty: true, signedIn: false } })

  test('a first launch signed out opens on Connect Claude, before the three steps, with nothing written', async ({ page, world }) => {
    await expect(connectHeading(page)).toBeVisible(LAUNCH)
    await expect(page.getByText('works through Claude, on your Pro or Max plan. It never uses an API key.')).toBeVisible()
    await expect(page.getByRole('navigation')).toHaveCount(0)
    await expect(progress(page).getByRole('listitem')).toHaveCount(3)
    await expect(current(page)).toHaveCount(0)
    await expect(signInButton(page)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Back', exact: true })).toHaveCount(0) // a first launch has nowhere to go back to
    expect(world.exists('profile')).toBe(false)
    expect(world.claudeCalls('draft')).toEqual([])
  })

  test('a wrong code fails with claude’s reason, Try again and the right code signs in and moves on to the sources', async ({ page, world }) => {
    await expect(connectHeading(page)).toBeVisible(LAUNCH)
    await startSignIn(page)
    await typeCode(page, 'wrong-code')
    await expect(page.getByRole('alert')).toHaveText("The sign-in didn't go through: Request failed with status code 400")
    expect(world.exists('profile')).toBe(false)

    await tryAgain(page).click()
    await expect(page.getByRole('alert')).toHaveCount(0)
    await expect(page.getByRole('status').filter({ hasText: 'Finish signing in' })).toBeVisible()
    await typeCode(page, 'world-code#ok')
    await expect(sourcesHeading(page)).toBeVisible(LAUNCH)
    // Signed in, the three steps begin: the sources are step 1 of 3.
    await expect(current(page)).toHaveAttribute('aria-label', 'Step 1 of 3')
    expect(readFileSync(join(world.dir, 'claude-login-args'), 'utf8')).toBe('auth login --claudeai')
    expect(world.exists('profile/config.json')).toBe(false)
  })

  test('a sign-in claude reports done but doctor does not confirm says so instead of checking forever', async ({ page, world }) => {
    await expect(connectHeading(page)).toBeVisible(LAUNCH)
    world.faults({ claude: { login: { stay_signed_out: true } } })
    await startSignIn(page)
    await typeCode(page, 'world-code#ok')
    await expect(page.getByRole('alert')).toHaveText("claude said the sign-in worked, but The other door still can't see the sign-in.", { timeout: 15_000 })
    await expect(tryAgain(page)).toBeVisible()
  })
})

test.describe('claude missing', () => {
  test.use({ worldOptions: { empty: true, noClaude: true } })

  test('an install that fails says why and offers Check again; installed by hand, Check again moves on', async ({ page, world }) => {
    await expect(connectHeading(page)).toBeVisible(LAUNCH)
    world.faults({ tools: { setup: { error: 'The download of claude failed: the network is unreachable' } } })
    await page.getByRole('button', { name: 'Install Claude', exact: true }).click()
    await page.getByRole('dialog', { name: 'Install Claude?' }).getByRole('button', { name: 'Install', exact: true }).click()
    await expect(page.getByRole('alert')).toHaveText('The download of claude failed: the network is unreachable')
    await expect(page.getByText('Installed it yourself?')).toBeVisible()
    expect(world.toolCalls('setup').map((c) => c.args)).toEqual([expect.objectContaining({ install: ['claude'], yes: true })])

    world.installClaude() // signed in already, in this world
    await checkAgain(page).click()
    await expect(sourcesHeading(page)).toBeVisible(LAUNCH)
    await expect(current(page)).toHaveAttribute('aria-label', 'Step 1 of 3')
  })
})
