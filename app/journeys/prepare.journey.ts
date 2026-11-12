
import { mkdirSync, readFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import type { Page } from '@playwright/test'
import { cvTex } from '../test/world/tailor'
import { expect, test } from './fixtures'
import { card, ledgerEntry, letterTex, openMatch, pagesLoaded, postingHeading, toApplications } from './helpers/applications'

const VESTVIND = 'Senior Data Scientist, Production Forecasting'
const VESTVIND_KEY = 'vestvind-senior-ds-forecasting'
const KRONVEJ = 'Machine Learning Engineer, MLOps'
const KRONVEJ_KEY = 'kronvej-ml-engineer-mlops'
const SUNDLINE = 'Senior Data Scientist – Network Optimisation & Demand Forecasting Team'
const PREPARING_TIP = 'Preparing an application. Find new jobs again when it is done.'
const LEAVE = 'You can leave this open; it takes a few minutes.'

const readyHeading = (page: Page) => page.getByRole('heading', { name: 'Ready to send', level: 1 })
const findButton = (page: Page) => page.getByRole('button', { name: 'Find new jobs', exact: true })

/** Clicks Prepare application and waits until the Prepare has ended (the running block is gone). */
async function prepareAndWait(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Prepare application', exact: true }).click()
  await expect(page.getByText(LEAVE)).toBeVisible()
  await expect(page.getByText(LEAVE)).toBeHidden({ timeout: 90_000 })
  await expect(findButton(page)).toBeEnabled()
}

/** Prepares the Vestvind match from Matches and lands on Ready to send. */
async function prepareVestvind(page: Page): Promise<void> {
  await openMatch(page, VESTVIND)
  await page.getByRole('button', { name: 'Prepare application', exact: true }).click()
  await expect(readyHeading(page)).toBeVisible({ timeout: 90_000 })
}

/** Opens Kronvej's prepared application from the board (FULL_LEDGER: prepared, with materials). */
async function openKronvejMaterials(page: Page): Promise<void> {
  await toApplications(page)
  await card(page, KRONVEJ).click()
  await expect(postingHeading(page, KRONVEJ)).toBeVisible()
  await page.getByRole('button', { name: 'See the application', exact: true }).click()
  await expect(readyHeading(page)).toBeVisible()
  await pagesLoaded(page, 'Letter', 1)
}

const outDir = (world: { home: string; jobId(k: string): string }, key: string) => join(world.home, 'jobs', 'output', world.jobId(key))

// --------------------------------------------------------------------------- §3 Prepare

test('Prepare application on a new match tailors, compiles and opens Ready to send', { tag: '@core' }, async ({ page, world }) => {
  await openMatch(page, VESTVIND)
  expect(ledgerEntry(world, VESTVIND_KEY)).toBeUndefined()
  await page.getByRole('button', { name: 'Prepare application', exact: true }).click()

  await expect(readyHeading(page)).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText(`${VESTVIND} · Vestvind Service A/S`, { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Letter · \d+ words$/ })).toHaveAttribute('aria-pressed', 'true')
  await pagesLoaded(page, 'Letter', 1)

  const id = world.jobId(VESTVIND_KEY)
  expect(ledgerEntry(world, VESTVIND_KEY)?.status).toBe('prepared')
  for (const f of ['cv.tex', 'cover_letter.tex', 'cv.pdf', 'cover_letter.pdf', 'facts.json', 'cv_page_1.png', 'cover_letter_page_1.png'])
    expect(world.exists(`jobs/output/${id}/${f}`), f).toBe(true)
  // compile filled in the posting's title and company
  expect(readFileSync(join(outDir(world, VESTVIND_KEY), 'cover_letter.tex'), 'utf8')).toContain('Vestvind Service A/S')
  expect(world.claudeCalls('tailor')).toHaveLength(1)
  expect(world.toolCalls('prepare')).toHaveLength(1)
  expect(world.toolCalls('prepare')[0]!.args).toMatchObject({ job_id: id, force: false })
})

test('while Prepare runs: the progress line, the elapsed time, locked actions and no Find new jobs', async ({ page, world }) => {
  world.faults({ claude: { tailor: { delay_s: 6 } } })
  await openMatch(page, VESTVIND)
  await page.getByRole('button', { name: 'Prepare application', exact: true }).click()

  const pane = page.getByRole('article')
  await expect(pane.getByRole('status')).toHaveText(/^(Preparing…|Writing your CV and cover letter)$/)
  await expect(pane.getByRole('status')).toHaveText('Writing your CV and cover letter')
  await expect(page.getByText(/^Elapsed 0:0\d$/)).toBeVisible()
  await expect(page.getByText(LEAVE)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Prepare application' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Open in browser' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Status', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Not for me' })).toBeDisabled()
  await expect(findButton(page)).toBeDisabled()
  await expect(findButton(page)).toHaveAttribute('title', PREPARING_TIP)

  await expect(readyHeading(page)).toBeVisible({ timeout: 90_000 })
  await expect(findButton(page)).toBeEnabled()
  expect(ledgerEntry(world, VESTVIND_KEY)?.status).toBe('prepared')
})

test('a failing tailor: Prepare says what went wrong and the job stays unprepared', async ({ page, world }) => {
  world.faults({ claude: { tailor: { fail: 'You have reached your usage limit.' } } })
  await openMatch(page, VESTVIND)
  await prepareAndWait(page)
  expect(ledgerEntry(world, VESTVIND_KEY)).toBeUndefined()
  expect(world.claudeCalls('tailor')).toHaveLength(1)
  await expect(page.getByRole('alert')).toContainText(/tailor step failed.*usage limit/, { timeout: 10_000 })
  await expect(postingHeading(page, VESTVIND)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Prepare application', exact: true })).toBeEnabled()
})

test('the server dying during Prepare says so, and the next Prepare works', async ({ page, world }) => {
  await openMatch(page, VESTVIND)
  world.faults({ tools: { prepare: { crash: true, once: true } } })
  await page.getByRole('button', { name: 'Prepare application', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveText("The other door's server stopped; try again")
  await expect(findButton(page)).toBeEnabled()
  expect(ledgerEntry(world, VESTVIND_KEY)).toBeUndefined()

  world.clearFaults()
  await page.getByRole('button', { name: 'Prepare application', exact: true }).click()
  await expect(readyHeading(page)).toBeVisible({ timeout: 90_000 })
  expect(ledgerEntry(world, VESTVIND_KEY)?.status).toBe('prepared')
})

test('Prepare again asks first; Cancel and Escape leave the application as it is', async ({ page, world }) => {
  await toApplications(page)
  await card(page, KRONVEJ).click()
  await expect(postingHeading(page, KRONVEJ)).toBeVisible()
  const before = readFileSync(join(outDir(world, KRONVEJ_KEY), 'cv.tex'), 'utf8')

  await page.getByRole('button', { name: 'Prepare again', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Prepare again?' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('This replaces the tailored CV and letter, and any revisions.')).toBeVisible()
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toHaveCount(0)

  await page.getByRole('button', { name: 'Prepare again', exact: true }).click()
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(postingHeading(page, KRONVEJ)).toBeVisible()

  expect(world.toolCalls('prepare')).toHaveLength(0)
  expect(readFileSync(join(outDir(world, KRONVEJ_KEY), 'cv.tex'), 'utf8')).toBe(before)
})

test('Prepare again replaces the application with a new one', async ({ page, world }) => {
  world.faults({ claude: { tailor: { cover_letter: letterTex(300) } } })
  await toApplications(page)
  await card(page, KRONVEJ).click()
  await page.getByRole('button', { name: 'Prepare again', exact: true }).click()
  await page.getByRole('dialog', { name: 'Prepare again?' }).getByRole('button', { name: 'Prepare again' }).click()

  await expect(readyHeading(page)).toBeVisible({ timeout: 90_000 })
  await expect(page.getByRole('button', { name: 'Letter · 300 words' })).toBeVisible()
  expect(world.toolCalls('prepare')[0]!.args).toMatchObject({ job_id: world.jobId(KRONVEJ_KEY), force: true })
  expect(world.claudeCalls('tailor')).toHaveLength(1)
  expect(readFileSync(join(outDir(world, KRONVEJ_KEY), 'cover_letter.tex'), 'utf8')).toBe(letterTex(300))
  expect(ledgerEntry(world, KRONVEJ_KEY)?.status).toBe('prepared')
})

// --------------------------------------------------------------------------- §5 Ready to send

test('Ready to send: the letter first, the CV behind the switch, every page loaded', async ({ page }) => {
  await openKronvejMaterials(page)
  await expect(page.getByText(`${KRONVEJ} · Kronvej`, { exact: true })).toBeVisible()
  const letter = page.getByRole('button', { name: /^Letter · \d+ words$/ })
  const cv = page.getByRole('button', { name: 'CV · 2 pages' })
  await expect(letter).toHaveAttribute('aria-pressed', 'true')
  await expect(cv).toHaveAttribute('aria-pressed', 'false')
  await expect(page.getByRole('note')).toHaveCount(0) // within the limits
  await expect(page.getByRole('button', { name: 'Save letter' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Anything to change?' })).toHaveAttribute('placeholder', 'Change the letter: make it shorter and warmer…')
  await expect(page.getByRole('button', { name: 'Revise' })).toBeDisabled()

  await cv.click()
  await expect(cv).toHaveAttribute('aria-pressed', 'true')
  await pagesLoaded(page, 'CV', 2)
  await expect(page.getByRole('img', { name: /^Letter/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Save CV' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Anything to change?' })).toHaveAttribute('placeholder', 'Change the CV: lead with the dashboards project…')
  await expect(page.getByRole('note')).toHaveCount(0)

  await page.getByRole('button', { name: '← Posting' }).click()
  await expect(postingHeading(page, KRONVEJ)).toBeVisible()
})

test('Save letter writes the PDF where the save dialog says', async ({ page, world, os }) => {
  await openKronvejMaterials(page)
  mkdirSync(join(world.scratch, 'saved'), { recursive: true })
  const target = join(world.scratch, 'saved', 'Mette letter.pdf')
  await os.nextSave(target)
  await page.getByRole('button', { name: 'Save letter' }).click()
  await expect(page.getByRole('status')).toHaveText('Saved as Mette letter.pdf in saved.')
  expect(readFileSync(target).equals(readFileSync(join(outDir(world, KRONVEJ_KEY), 'cover_letter.pdf')))).toBe(true)
})

test('Revise changes the letter, shows the new pages, and Undo puts it back', async ({ page, world }) => {
  world.faults({ claude: { revise: { delay_s: 3 } } })
  await openKronvejMaterials(page)
  const tex = join(outDir(world, KRONVEJ_KEY), 'cover_letter.tex')
  const before = readFileSync(tex, 'utf8')
  const words = (await page.getByRole('button', { name: /^Letter · / }).textContent())!

  const box = page.getByRole('textbox', { name: 'Anything to change?' })
  await box.fill('Make it shorter.')
  await page.getByRole('button', { name: 'Revise' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Revising…' })).toBeVisible()
  await expect(box).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Undo last change' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Save letter' })).toBeDisabled()
  await expect(page.getByRole('button', { name: "I've applied" })).toBeDisabled()
  await expect(page.getByRole('button', { name: /^CV · / })).toBeDisabled()
  await expect(page.getByTestId('pages')).toHaveAttribute('aria-busy', 'true')

  await expect(box).toHaveValue('', { timeout: 60_000 })
  await expect(page.getByRole('button', { name: /^Letter · / })).not.toHaveText(words)
  await pagesLoaded(page, 'Letter', 1)
  expect(readFileSync(tex, 'utf8')).not.toBe(before)
  expect(world.toolCalls('revise')[0]!.args).toMatchObject({ job_id: world.jobId(KRONVEJ_KEY), file: 'cover_letter', instruction: 'Make it shorter.' })
  expect(world.claudeCalls('revise')).toHaveLength(1)

  await page.getByRole('button', { name: 'Undo last change' }).click()
  await expect(page.getByRole('button', { name: /^Letter · / })).toHaveText(words, { timeout: 60_000 })
  expect(readFileSync(tex, 'utf8')).toBe(before)
  expect(world.toolCalls('revise')[1]!.args).toMatchObject({ file: 'cover_letter', undo: true })
})

test('Ready to send names the claims the CV does not back', async ({ page, world }) => {
  world.faults({ claude: { tailor: { cv: cvTex(world.persona).replace('\\end{document}', 'Cut forecast error by 87% across 140 wind parks.\n\n\\end{document}') } } })
  await prepareVestvind(page)
  const facts = world.readJson<{ value: string }[] | { unsupported: { value: string }[] }>(`jobs/output/${world.jobId(VESTVIND_KEY)}/facts.json`)
  expect(JSON.stringify(facts)).toContain('87')
  await expect(page.getByText(/\b87\b/)).toBeVisible({ timeout: 5_000 })
})

test("I've applied from Matches names the job in its notice", async ({ page, world }) => {
  await prepareVestvind(page)
  await page.getByRole('button', { name: "I've applied" }).click()
  await expect.poll(() => ledgerEntry(world, VESTVIND_KEY)?.status).toBe('applied')
  await expect(page.getByRole('status')).toHaveText(`Applied: ${VESTVIND}. It is in Applications now.`, { timeout: 5_000 })
})

test("I've applied records the application in one click and keeps a copy of what was sent", { tag: '@core' }, async ({ page, world }) => {
  await openKronvejMaterials(page)
  await page.getByRole('button', { name: "I've applied" }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)

  await expect(page.getByRole('status')).toHaveText(`Applied: ${KRONVEJ}. It is in Applications now.`)
  await expect(page.getByRole('region', { name: 'Applied' }).getByRole('button', { name: new RegExp(`^${KRONVEJ}`) })).toBeVisible()
  const entry = ledgerEntry(world, KRONVEJ_KEY)!
  expect(entry.status).toBe('applied')
  expect(Object.keys(entry.materials ?? {})).toEqual(expect.arrayContaining(['cv.pdf', 'cover_letter.pdf']))
  expect(world.exists(`jobs/output/${world.jobId(KRONVEJ_KEY)}/sent/cv.pdf`)).toBe(true)
  expect(world.toolCalls('set_status')[0]!.args).toMatchObject({ job_id: world.jobId(KRONVEJ_KEY), status: 'applied' })
})

test('What you sent: the copy kept when it went out, read only, and saved from there', async ({ page, world, os }) => {
  await toApplications(page)
  await card(page, SUNDLINE).click()
  await expect(postingHeading(page, SUNDLINE)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Prepare again' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Not for me' })).toHaveCount(0)
  await page.getByRole('button', { name: 'See what you sent', exact: true }).click()

  await expect(page.getByRole('heading', { name: 'What you sent', level: 1 })).toBeVisible()
  await expect(page.getByText(`${SUNDLINE} · Sundline Shipping`, { exact: true })).toBeVisible()
  await pagesLoaded(page, 'Letter', 1)
  await expect(page.getByRole('img', { name: 'Letter, page 1' })).toHaveAttribute('src', new RegExp(`/${world.jobId('sundline-network-optimisation')}/sent/cover_letter_page_1\\.png`))
  await expect(page.getByRole('button', { name: "I've applied" })).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: 'Anything to change?' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Undo last change' })).toHaveCount(0)
  await page.getByRole('button', { name: 'CV · 2 pages' }).click()
  await pagesLoaded(page, 'CV', 2)

  mkdirSync(join(world.scratch, 'saved'), { recursive: true })
  const target = join(world.scratch, 'saved', 'sent CV.pdf')
  await os.nextSave(target)
  await page.getByRole('button', { name: 'Save CV' }).click()
  await expect(page.getByRole('status')).toHaveText('Saved as sent CV.pdf in saved.')
  expect(readFileSync(target).equals(readFileSync(join(outDir(world, 'sundline-network-optimisation'), 'sent', 'cv.pdf')))).toBe(true)
})

test('What you sent for a job whose sent copy is missing still shows and saves its pages', async ({ page, world, os }) => {
  rmSync(join(outDir(world, 'sundline-network-optimisation'), 'sent'), { recursive: true })
  await toApplications(page)
  await card(page, SUNDLINE).click()
  await page.getByRole('button', { name: /^See (what you sent|the application)$/ }).click()
  await expect(page.getByRole('heading', { name: /^(What you sent|Ready to send)$/, level: 1 })).toBeVisible()
  mkdirSync(join(world.scratch, 'saved'), { recursive: true })
  const target = join(world.scratch, 'saved', 'letter.pdf')
  await os.nextSave(target)
  await page.getByRole('button', { name: 'Save letter' }).click()
  await expect(page.getByRole('status')).toHaveText('Saved as letter.pdf in saved.', { timeout: 10_000 })
  await pagesLoaded(page, 'Letter', 1)
})
