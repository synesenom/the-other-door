// The first launch, end to end in the built app: DOOR_ONBOARD_DIR (a temp folder) makes the unpackaged
// app an onboarding sandbox, an empty home. The wizard is walked with the real server; the stand-in claude
// first on PATH answers its model calls from scripted files (`answerOnboarding`), or fails where a test wants
// that. The first run is the simulated one (DOOR_DEMO_RUN_MS makes it short). The real jobs/, profile/,
// app/.demo and app/.onboard are never touched.
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { _electron as electron, expect, test } from '@playwright/test'
import type { ElectronApplication, Page } from '@playwright/test'
import { answerOnboarding, buildEmptyHome, repoRoot } from '../test/home-fixture'

const APP = resolve(__dirname, '..')
const CV = '# Ada Lovelace\n\n**Email:** ada@example.com | **Location:** Copenhagen\n\nData scientist with ten years of analysis.\n'
const CV_NO_CITY = '# Ada Lovelace\n\n**Email:** ada@example.com\n\nData scientist with ten years of analysis. Taler dansk.\n'

/** What the real data folders look like: a change here means the test reached outside its sandbox. */
function snapshot(): string {
  const parts: string[] = []
  for (const dir of [join(repoRoot, 'profile'), join(repoRoot, 'jobs'), join(APP, '.demo'), join(APP, '.onboard')]) {
    if (!existsSync(dir)) {
      parts.push(`${dir}: absent`)
      continue
    }
    const entries = readdirSync(dir, { recursive: true, encoding: 'utf8' }).sort()
    parts.push(`${dir}: ${entries.map((e) => `${e}@${statSync(join(dir, e)).mtimeMs}`).join(',')}`)
  }
  return parts.join('\n')
}

async function launch(fixture: ReturnType<typeof buildEmptyHome>, sandbox: string): Promise<ElectronApplication> {
  return electron.launch({
    args: ['.', ...(process.env.CI ? ['--no-sandbox'] : [])],
    cwd: APP,
    env: { ...(process.env as Record<string, string>), ...fixture.env, DOOR_ONBOARD_DIR: sandbox, DOOR_DEMO_RUN_MS: '4000' },
  })
}

/** Signs in on the Connect Claude step: the stand-in claude is signed out. A wrong code fails, the right one signs in. */
async function signIn(page: Page, fixture: ReturnType<typeof buildEmptyHome>) {
  await page.getByRole('button', { name: 'Sign in with Claude' }).click({ timeout: 30_000 })
  await expect(page.getByText(/Finish signing in in your browser/)).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('button', { name: 'Open the sign-in page again' })).toBeEnabled()
  await page.getByRole('button', { name: 'The page showed a code?' }).click()
  await page.getByLabel('Sign-in code').fill('wrong-code')
  await page.getByRole('button', { name: 'Send code' }).click()
  await expect(page.getByRole('alert')).toContainText("didn't go through: Request failed with status code 400")
  await page.getByRole('button', { name: 'Try again' }).click()
  await page.getByRole('button', { name: 'The page showed a code?' }).click()
  await page.getByLabel('Sign-in code').fill('stand-in-code#ok')
  await page.getByRole('button', { name: 'Send code' }).click()
  await expect(page.getByRole('button', { name: 'Sign in with Claude' })).toHaveCount(0, { timeout: 30_000 })
  await expect(page.getByLabel('Sign-in code')).toHaveCount(0)
  expect(readFileSync(join(fixture.scratch, 'claude-login-args'), 'utf8').trim()).toContain('auth login --claudeai')
}

/** Adds a CV through the stubbed file dialog (no production hook) and a page, and refuses LinkedIn. */
async function giveSources(app: ElectronApplication, page: Page, fixture: ReturnType<typeof buildEmptyHome>) {
  const mine = join(fixture.scratch, 'my-cv.md')
  writeFileSync(mine, '# Ada Lovelace\n\nData scientist.\n')
  await app.evaluate(({ dialog }, path) => {
    dialog.showOpenDialog = (async () => ({ canceled: false, filePaths: [path] })) as unknown as typeof dialog.showOpenDialog
  }, mine)
  await page.getByRole('button', { name: 'Drop relevant documents here (CV or LinkedIn PDF)' }).click()
  await expect(page.getByText('my-cv.md', { exact: true })).toBeVisible()
  await page.getByLabel('Any relevant URL').fill('https://www.linkedin.com/in/ada')
  await page.getByLabel('Any relevant URL').press('Enter')
  await expect(page.getByRole('alert')).toContainText('Save to PDF')
  await page.getByLabel('Any relevant URL').fill('https://ada.dev')
  await page.getByLabel('Any relevant URL').press('Enter')
}

test('a good CV goes from the sources to the review, Save and a first run, asking nothing else', async () => {
  const fixture = buildEmptyHome()
  test.skip(!fixture.hasPython, `no Python at ${fixture.python} (set DOOR_PYTHON)`)
  answerOnboarding(fixture.scratch, CV, null)
  const before = snapshot()
  const sandbox = join(fixture.scratch, 'onboard')
  const app = await launch(fixture, sandbox)
  try {
    const page = await app.firstWindow()
    await expect(page.getByRole('heading', { name: 'Connect Claude', level: 1 })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByRole('navigation')).toHaveCount(0)
    expect(existsSync(join(sandbox, 'profile', 'config.json'))).toBe(false) // nothing written yet

    await signIn(page, fixture)
    await expect(page.getByRole('heading', { name: 'Tell me about yourself', level: 1 })).toBeVisible({ timeout: 30_000 })
    await giveSources(app, page, fixture)
    await page.getByRole('button', { name: 'Continue' }).click()

    await expect(page.getByRole('heading', { name: 'Check your answers', level: 1 })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Ada Lovelace')
    await expect(page.getByLabel('Email')).toHaveValue('ada@example.com')
    await expect(page.getByLabel('City', { exact: true })).toHaveValue('Copenhagen')
    await expect(page.getByRole('checkbox', { name: /Data Scientist your latest title/ })).toBeChecked()
    await expect(page.getByRole('checkbox', { name: /Quant your maths/ })).not.toBeChecked()
    await expect(page.getByRole('checkbox', { name: 'LinkedIn' })).not.toBeChecked()
    expect(existsSync(join(sandbox, 'profile', 'config.json'))).toBe(false) // still nothing written

    await page.getByRole('checkbox', { name: 'LinkedIn' }).check()
    await page.getByRole('button', { name: 'Save and start searching' }).click()

    await expect(page.getByRole('heading', { name: 'Finding jobs', level: 1 })).toBeVisible({ timeout: 30_000 })
    expect(readFileSync(join(sandbox, 'profile', 'cv.md'), 'utf8')).toBe(CV)
    const config = JSON.parse(readFileSync(join(sandbox, 'profile', 'config.json'), 'utf8'))
    expect(config).toMatchObject({
      name: 'Ada Lovelace', email: 'ada@example.com', location: 'Copenhagen', remote: 'hybrid', languages: ['English'],
      role_targets: ['Data Scientist'], search_keywords: ['data scientist', 'ml engineer'], topic_terms: ['data'],
      linkedin_discovery: true, enrich_sources: ['https://ada.dev'], exclude: { companies: [], keywords: [] },
    })
    await page.getByRole('button', { name: /View .*matches/i }).click({ timeout: 60_000 })
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible()
    await expect(page.getByText('Finance Controller')).toBeVisible()
    await expect(page.getByRole('note', { name: 'Onboarding sandbox' })).toBeVisible()
  } finally {
    await app.close()
  }
  expect(snapshot()).toBe(before)
})

test('a CV with no city leaves only the city for the review', async () => {
  const fixture = buildEmptyHome()
  test.skip(!fixture.hasPython, `no Python at ${fixture.python} (set DOOR_PYTHON)`)
  answerOnboarding(fixture.scratch, CV_NO_CITY, null)
  writeFileSync(join(fixture.scratch, 'claude-signed-in'), '')
  const sandbox = join(fixture.scratch, 'onboard')
  const app = await launch(fixture, sandbox)
  try {
    const page = await app.firstWindow()
    await expect(page.getByRole('heading', { name: 'Tell me about yourself', level: 1 })).toBeVisible({ timeout: 60_000 })
    await giveSources(app, page, fixture)
    await page.getByRole('button', { name: 'Continue' }).click()

    await expect(page.getByRole('heading', { name: 'Check your answers', level: 1 })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('These could not be found in your sources: your city.', { exact: false })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Save and start searching' })).toBeDisabled()
    await page.getByLabel('City', { exact: true }).selectOption('Aarhus')
    await expect(page.getByText('could not be found')).toHaveCount(0)
    await expect(page.getByRole('checkbox', { name: 'Danish' })).toBeChecked() // the CV lists it at a working level
  } finally {
    await app.close()
  }
})

test('with a failing claude, what it would have read is left to fill in at the review', async () => {
  const fixture = buildEmptyHome()
  test.skip(!fixture.hasPython, `no Python at ${fixture.python} (set DOOR_PYTHON)`)
  writeFileSync(join(fixture.scratch, 'claude-signed-in'), '')
  const sandbox = join(fixture.scratch, 'onboard')
  const app = await launch(fixture, sandbox)
  try {
    const page = await app.firstWindow()
    await expect(page.getByRole('heading', { name: 'Tell me about yourself', level: 1 })).toBeVisible({ timeout: 60_000 })
    await giveSources(app, page, fixture)
    await page.getByRole('button', { name: 'Continue' }).click()
    await expect(page.getByRole('alert')).toContainText('could not be read', { timeout: 60_000 })
    await page.getByRole('button', { name: 'Go on without a draft' }).click()

    await expect(page.getByRole('heading', { name: 'Check your answers', level: 1 })).toBeVisible({ timeout: 60_000 })
    await page.getByLabel('Name', { exact: true }).fill('Ada Lovelace')
    await page.getByLabel('Email', { exact: true }).fill('ada@example.com')
    await page.getByLabel('City', { exact: true }).selectOption('Copenhagen')
    await page.getByLabel('Add your own title').fill('Data Scientist')
    await page.getByLabel('Add your own title').press('Enter')

    // Nothing could draft a CV: it is asked for here, and only then does Save start the run.
    await expect(page.getByRole('button', { name: 'Save and start searching' })).toBeDisabled()
    await page.getByLabel('Your CV', { exact: true }).fill('# Ada Lovelace\n')
    await page.getByRole('button', { name: 'Save and start searching' }).click()
    await expect(page.getByRole('heading', { name: 'Finding jobs', level: 1 })).toBeVisible({ timeout: 30_000 })
    const config = JSON.parse(readFileSync(join(sandbox, 'profile', 'config.json'), 'utf8'))
    expect(config).toMatchObject({ name: 'Ada Lovelace', role_targets: ['Data Scientist'], search_keywords: ['Data Scientist'] })
  } finally {
    await app.close()
  }
})
