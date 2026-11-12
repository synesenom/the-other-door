
import type { Page } from '@playwright/test'
import type { World } from '../test/world/build'
import { expect, test } from './fixtures'
import {
  halfWaySteps,
  holdLedgerLock,
  postingOf,
  runButton,
  runRecords,
  setBoard,
  stepDone,
  stepRow,
  steps,
  unsetConfig,
} from './helpers/finding'

// Matches' tip while a Prepare runs (the screen module is not loaded here: it imports Vite-only modules).
const PREPARING_TIP = 'Preparing an application. Find new jobs again when it is done.'

const FRESH_ABOVE = ['havtorn-lead-ds', 'varmevaerk-ost-varmeprognoser'] // 0.89 and 0.76: above min_score 0.65
const FRESH_BELOW = 'nordlys-retail-marketing-analyst' // 0.48
/** A run of another process, started at 09:30 world time (10:30 in Copenhagen). */
const ELSEWHERE_STARTED = '2026-10-26T09:30:00+00:00'

const ready = (page: Page) => expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible({ timeout: 60_000 })
const findingHeading = (page: Page) => page.getByRole('heading', { name: 'Finding jobs', level: 1 })
const summary = (page: Page) => page.getByRole('region', { name: 'Run summary' })
const record = (world: World, name: string) => world.readJson(`jobs/runs/${name}`)
const nav = (page: Page, name: string) => page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name })
const matchRow = (page: Page, company: string) => page.getByRole('main').getByRole('list').first().getByRole('button').filter({ hasText: company })

/** Scoring waits, so a run stays on its Match step (search, follow and collect done) for `delay_s`. */
async function runUntilMatch(page: Page, world: World, delay_s = 12) {
  world.faults({ claude: { score: { delay_s } } })
  await runButton(page).click()
  await expect.poll(() => world.claudeCalls('score').length, { timeout: 60_000 }).toBeGreaterThan(0)
  await expect(stepDone(page, 'Collect')).toBeVisible()
}

/** Starts a run and waits for its summary. */
async function runToSummary(page: Page) {
  await runButton(page).click()
  await expect(summary(page)).toBeVisible({ timeout: 90_000 })
}

test.describe('a run', () => {
  test('Find new jobs runs the five steps against the boards, scores the new ads and sums the run up', { tag: '@core' }, async ({ page, world }) => {
    await ready(page)
    const before = runRecords(world)
    await expect(page.getByRole('complementary').getByText(/^Last run /)).toHaveText('Last run Oct 25, 02:41 PM')

    await runUntilMatch(page, world)
    // the screen while Match scores: the first four steps settled, Stop on the title's line
    await expect(findingHeading(page)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeEnabled()
    await expect(page.getByText(/^Started \d\d:\d\d (AM|PM) · you can switch screens while it runs; quitting The other door stops it\.$/)).toBeVisible()
    await expect(steps(page).getByRole('listitem')).toHaveCount(5)
    await expect(stepDone(page, 'Search')).toBeVisible()
    await expect(stepRow(page, 'Search').getByText('3 postings from 3 boards', { exact: true })).toBeVisible()
    await expect(stepRow(page, 'Discover').getByText('Skipped', { exact: true })).toBeVisible()
    await expect(stepDone(page, 'Follow')).toBeVisible()
    await expect(stepRow(page, 'Collect').getByText('7 employers, 0 postings', { exact: true })).toBeVisible()
    await expect(stepDone(page, 'Match')).toHaveCount(0)
    await expect(stepRow(page, 'Match').getByText('Scores the new ads against your CV')).toHaveCount(0)
    // the sidebar's button says a run is going, and is off while its screen is open
    await expect(runButton(page)).toHaveText('Finding jobs…')
    await expect(runButton(page)).toBeDisabled()
    // Match's line is the last progress event written before scoring ("dedup" or "0 of 3 scored", throttled): masked

    await expect(summary(page)).toBeVisible({ timeout: 60_000 })
    await expect(page.getByRole('button', { name: 'Stop', exact: true })).toHaveCount(0)
    await expect(steps(page)).toHaveCount(0)
    const top = summary(page).getByRole('listitem')
    await expect(top.filter({ hasText: 'Havtorn Energi' })).toContainText('Lead Data Scientist')
    await expect(top.filter({ hasText: 'Havtorn Energi' })).toContainText('0.89')
    await expect(top.filter({ hasText: 'Varmeværk Øst I/S' })).toContainText('0.76')
    await expect(top.filter({ hasText: 'Nordlys Retail' })).toHaveCount(0)
    await expect(summary(page).getByText(/^Took \d+ s$/)).toBeVisible()
    await expect(summary(page).getByRole('button', { name: 'View matches' })).toBeVisible()
    await expect(summary(page).getByRole('button', { name: 'Show run record' })).toBeVisible()
    await expect(runButton(page)).toHaveText('Find new jobs')
    await expect(runButton(page)).toBeEnabled()
    await expect(page.getByRole('complementary').getByText(/^Last run /)).toHaveText(/^Last run Oct 26, \d\d:\d\d (AM|PM)$/)

    // the disk: a record of the run, the fresh ads stored and scored
    const after = runRecords(world)
    expect(after.length).toBe(before.length + 1)
    const rec = record(world, after[after.length - 1])
    expect(rec.steps).toEqual(['search', 'follow', 'collect', 'match'])
    expect(rec.failures).toEqual([])
    expect(rec.match.summary).toBe('3 scored, 2 above 0.65')
    for (const key of FRESH_ABOVE) expect(rec.new_above_threshold).toContain(world.jobId(key))
    expect(rec.new_above_threshold).not.toContain(world.jobId(FRESH_BELOW))
    expect(postingOf(world, world.jobId('havtorn-lead-ds'))?.score).toBe(0.89)
    expect(postingOf(world, world.jobId('varmevaerk-ost-varmeprognoser'))?.score).toBe(0.76)
    expect(postingOf(world, world.jobId(FRESH_BELOW))?.score).toBe(0.48)
    expect(world.exists('jobs/.lock.json')).toBe(false)
    // one find_jobs, and nothing else was asked for
    expect(world.toolCalls('find_jobs')).toHaveLength(1)
    expect(world.toolCalls('find_jobs')[0].args).toMatchObject({ step: null, skip: null, boards: null, company: null })
    expect(world.toolCalls('prepare')).toHaveLength(0)
    expect(world.claudeCalls('tailor')).toHaveLength(0)
  })

  test('the summary counts the new matches of this run and lists only them', async ({ page, world }) => {
    await ready(page)
    await runToSummary(page)
    await expect(summary(page).getByRole('heading', { level: 2 })).toHaveText('2 new matches')
    await expect(summary(page).getByRole('listitem')).toHaveCount(2)
    expect(world.toolCalls('find_jobs')).toHaveLength(1)
  })

  test('View matches opens Matches on New only, with the ads the run found', { tag: '@core' }, async ({ page, world }) => {
    await ready(page)
    await runToSummary(page)
    await summary(page).getByRole('button', { name: 'View matches' }).click()
    await ready(page)
    await expect(findingHeading(page)).toHaveCount(0)
    await expect(page.getByRole('switch', { name: 'New only' })).toHaveAttribute('aria-checked', 'true')
    await expect(nav(page, 'Matches')).toHaveAttribute('aria-current', 'page')
    await expect(matchRow(page, 'Havtorn Energi')).toHaveCount(1)
    await expect(matchRow(page, 'Varmeværk Øst I/S')).toContainText('Data Scientist for heat demand forecasts')
    await expect(matchRow(page, 'Nordlys Retail')).toHaveCount(0)
    // every row shown is new
    const rows = page.getByRole('main').getByRole('list').first().getByRole('button')
    for (const row of await rows.all()) await expect(row.getByRole('img', { name: 'New since your last review' })).toBeVisible()
  })
})

test.describe('a second run', () => {
  test('a second run reads the boards again and scores nothing twice', async ({ page, world }) => {
    await ready(page)
    await runToSummary(page)
    const scored = world.claudeCalls('score').length
    // the sidebar's button starts the next one from the summary
    await runButton(page).click()
    await expect.poll(() => world.toolCalls('find_jobs').length).toBe(2)
    await expect(summary(page)).toBeVisible({ timeout: 90_000 })
    await expect.poll(() => runRecords(world).length).toBe(3)
    const second = record(world, runRecords(world).at(-1)!)
    expect(second.match.summary).toMatch(/^0 scored/)
    expect(world.claudeCalls('score').length).toBe(scored)
  })

  test('a second run that found nothing new says No new matches', async ({ page, world }) => {
    await ready(page)
    await runToSummary(page)
    await runButton(page).click()
    await expect.poll(() => runRecords(world).length).toBe(3)
    await expect(summary(page).getByRole('heading', { level: 2 })).toHaveText('No new matches')
    await expect(summary(page).getByRole('listitem')).toHaveCount(0)
  })
})

test.describe('Stop', () => {
  test('Stop ends the run: back on Matches, no run record, the ads it found kept for the next run', async ({ page, world }) => {
    await ready(page)
    const before = runRecords(world)
    const ledger = world.readJson('jobs/applications.json')
    await runUntilMatch(page, world, 60)
    await page.getByRole('button', { name: 'Stop', exact: true }).click()
    // the window is back where the run was started from, with nothing to say
    await ready(page)
    await expect(findingHeading(page)).toHaveCount(0)
    await expect(page.getByRole('alert')).toHaveCount(0)
    await expect(runButton(page)).toHaveText('Find new jobs')
    await expect(runButton(page)).toBeEnabled()
    await expect(matchRow(page, 'Baltic Power Trading ApS')).toBeVisible()

    // the disk: no record, the found ads kept unscored, the ledger as it was
    expect(runRecords(world)).toEqual(before)
    expect(postingOf(world, world.jobId('havtorn-lead-ds'))).not.toBeNull()
    expect(postingOf(world, world.jobId('havtorn-lead-ds'))?.score ?? null).toBeNull()
    expect(world.readJson('jobs/applications.json')).toEqual(ledger)

    // the next run picks up where this one stopped: it scores what the stopped one found
    world.clearFaults()
    await runToSummary(page)
    expect(postingOf(world, world.jobId('havtorn-lead-ds'))?.score).toBe(0.89)
    expect(runRecords(world)).toHaveLength(before.length + 1)
  })
})

test.describe('a board that fails', () => {
  test('a board that fails: the run still ends in a summary and its record names the board', async ({ page, world }) => {
    await ready(page)
    setBoard(world, 'jobindex', { fail: 'jobindex answered 503 Service Unavailable' })
    await runToSummary(page)
    const rec = record(world, runRecords(world).at(-1)!)
    expect(rec.failures).toEqual(['jobindex'])
    const site = rec.search.sites.find((s: { site: string }) => s.site === 'jobindex')
    expect(site.outcome).toBe('failed')
    expect(site.errors).toEqual(['jobindex answered 503 Service Unavailable'])
    expect(postingOf(world, world.jobId('havtorn-lead-ds'))).toBeNull()
  })

  // Not said on purpose (#478): the user cannot act on it, and the next run reads the board again.
  test('the summary does not mention the board that could not be read', async ({ page, world }) => {
    await ready(page)
    setBoard(world, 'jobindex', { fail: 'jobindex answered 503 Service Unavailable' })
    await runToSummary(page)
    await expect(summary(page).getByText(/jobindex|could not be read/i)).toHaveCount(0)
  })
})

test.describe('scoring that fails', () => {
  test('scoring that fails: the ads stay on disk unscored and the record lists them as failed', async ({ page, world }) => {
    await ready(page)
    world.faults({ claude: { score: { fail: 'Claude usage limit reached' } } })
    await runToSummary(page)
    const rec = record(world, runRecords(world).at(-1)!)
    const fresh = [...FRESH_ABOVE, FRESH_BELOW].map((k) => world.jobId(k)).sort()
    expect([...rec.match.failed].sort()).toEqual(fresh)
    expect([...rec.failures].sort()).toEqual(fresh)
    for (const id of fresh) expect(postingOf(world, id)?.score ?? null).toBeNull()
    // the next run scores them
    world.clearFaults()
    await runButton(page).click()
    await expect.poll(() => runRecords(world).length).toBe(3)
    expect(postingOf(world, world.jobId('havtorn-lead-ds'))?.score).toBe(0.89)
  })

  // Not said on purpose (#478): the user cannot act on it, and the next run scores them.
  test('the summary does not mention the ads that could not be scored', async ({ page, world }) => {
    await ready(page)
    world.faults({ claude: { score: { fail: 'Claude usage limit reached' } } })
    await runToSummary(page)
    await expect(summary(page).getByText(/not (be )?scored/i)).toHaveCount(0)
  })
})

test.describe('find_jobs failing', () => {
  test('find_jobs answering an error: the alert says why, nothing is written, and Find new jobs runs again', async ({ page, world }) => {
    await ready(page)
    const before = runRecords(world)
    world.faults({ tools: { find_jobs: { error: 'Your profile could not be read: min_score must be between 0 and 1' } } })
    await runButton(page).click()
    const alert = page.getByRole('alert')
    await expect(alert).toHaveText('The other door could not start the run: Your profile could not be read: min_score must be between 0 and 1')
    await expect(findingHeading(page)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Stop', exact: true })).toHaveCount(0)
    await expect(steps(page)).toHaveCount(0)
    const again = page.getByRole('main').getByRole('button', { name: 'Find new jobs' })
    await expect(again).toBeEnabled()
    await expect(runButton(page)).toHaveText('Find new jobs')
    expect(runRecords(world)).toEqual(before)
    expect(postingOf(world, world.jobId('havtorn-lead-ds'))).toBeNull()

    world.clearFaults()
    await again.click()
    await expect(summary(page)).toBeVisible({ timeout: 90_000 })
    await expect(page.getByRole('alert')).toHaveCount(0)
    expect(runRecords(world)).toHaveLength(before.length + 1)
    expect(world.toolCalls('find_jobs')).toHaveLength(2)
  })

  test('the server dying during the run: the alert says it stopped, and the next run starts a new one', async ({ page, world }) => {
    await ready(page)
    const before = runRecords(world)
    world.faults({ tools: { find_jobs: { crash: true } } })
    await runButton(page).click()
    await expect(page.getByRole('alert')).toHaveText("The other door could not start the run: The other door's server stopped; try again")
    expect(runRecords(world)).toEqual(before)

    world.clearFaults()
    await page.getByRole('main').getByRole('button', { name: 'Find new jobs' }).click()
    await expect(summary(page)).toBeVisible({ timeout: 90_000 })
    expect(runRecords(world)).toHaveLength(before.length + 1)
    expect(postingOf(world, world.jobId('havtorn-lead-ds'))?.score).toBe(0.89)
  })

  test('another process writing the ledgers: the alert names it, and the run works once it is done', async ({ page, world }) => {
    await ready(page)
    const holder = await holdLedgerLock(world, 'export', { startedAt: ELSEWHERE_STARTED })
    try {
      // nothing on the run board: the button is on
      await expect(runButton(page)).toHaveText('Find new jobs')
      await runButton(page).click()
      await expect(page.getByRole('alert')).toHaveText(
        new RegExp(`^The other door could not start the run: another process of The other door is writing the ledgers \\(export\\) \\(started \\d\\d:\\d\\d, pid ${holder.pid}\\); try again in a moment$`),
      )
      expect(runRecords(world)).toHaveLength(1)
    } finally {
      await holder.release()
    }
    await page.getByRole('main').getByRole('button', { name: 'Find new jobs' }).click()
    await expect(summary(page)).toBeVisible({ timeout: 90_000 })
  })
})

test.describe('a run started elsewhere', () => {
  test('a run started in a terminal: the window jumps to Finding jobs, read only, and comes back when it ends', async ({ page, world }) => {
    await ready(page)
    const holder = await holdLedgerLock(world, 'run', { startedAt: ELSEWHERE_STARTED, steps: halfWaySteps(ELSEWHERE_STARTED) })
    try {
      await expect(findingHeading(page)).toBeVisible()
      await expect(page.getByRole('status').filter({ hasText: 'A run started elsewhere' })).toHaveText('A run started elsewhere is in progress (started 10:30 AM)')
      await expect(page.getByRole('button', { name: 'Stop', exact: true })).toHaveCount(0)
      await expect(stepDone(page, 'Search')).toBeVisible()
      await expect(stepRow(page, 'Discover').getByText('Skipped', { exact: true })).toBeVisible()
      await expect(stepRow(page, 'Follow').getByText('1 of 4 candidates', { exact: true })).toBeVisible()
      await expect(page.getByRole('progressbar', { name: 'Follow progress' })).toHaveAttribute('aria-valuenow', '25')
      await expect(stepRow(page, 'Collect').getByText('Reads the career pages you follow')).toBeVisible()
      await expect(runButton(page)).toHaveText('Finding jobs…')
      await expect(runButton(page)).toBeDisabled()
      // the window can go elsewhere meanwhile; the button stays off
      await nav(page, 'Applications').click()
      await expect(findingHeading(page)).toHaveCount(0)
      await expect(runButton(page)).toBeDisabled()
      await nav(page, 'Matches').click()
      await ready(page)
    } finally {
      await holder.release()
    }
    // the run is over: the button is back, and the window did not start one of its own
    await expect(runButton(page)).toHaveText('Find new jobs')
    await expect(runButton(page)).toBeEnabled()
    await ready(page)
    expect(world.toolCalls('find_jobs')).toHaveLength(0)
  })
})

test.describe('a Prepare in progress', () => {
  test('a Prepare in progress turns Find new jobs off until it is done', async ({ page, world }) => {
    await ready(page)
    world.faults({ claude: { tailor: { delay_s: 8 } } })
    await matchRow(page, 'Baltic Power Trading ApS').click()
    await page.getByRole('button', { name: 'Prepare application' }).click()
    await expect(runButton(page)).toBeDisabled()
    await expect(runButton(page)).toHaveAttribute('title', PREPARING_TIP)
    await expect(runButton(page)).toHaveText('Find new jobs')
    await expect.poll(() => world.readJson('jobs/applications.json')[world.jobId('baltic-power-lead-ds')]?.status, { timeout: 60_000 }).toBe('prepared')
    await expect(runButton(page)).toBeEnabled({ timeout: 30_000 })
    await expect(runButton(page)).not.toHaveAttribute('title', /./)
    expect(world.toolCalls('find_jobs')).toHaveLength(0)
  })
})

test.describe('discovery sources never chosen', () => {
  test('the sources never chosen are said under Discover, and Enable opens Settings on Risky sources', async ({ page, world }) => {
    await ready(page)
    unsetConfig(world, ['linkedin_discovery'])
    await page.reload()
    await ready(page)
    await runUntilMatch(page, world, 30)
    await expect(stepRow(page, 'Discover').getByText('Skipped', { exact: true })).toBeVisible()
    const sources = page.getByRole('list', { name: 'Discover sources' })
    await expect(sources.getByRole('listitem')).toHaveText(['LinkedIn (not enabled, enable)'])

    await sources.getByRole('button', { name: 'Enable LinkedIn' }).click()
    await expect(findingHeading(page)).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'Risky sources', level: 2 })).toBeInViewport()
    // the run goes on; nothing was turned on behind the user's back
    await expect(runButton(page)).toHaveText('Finding jobs…')
    await expect(runButton(page)).toBeEnabled()
    const config = world.readJson('profile/config.json')
    expect(config.linkedin_discovery).toBeUndefined()
    expect(world.toolCalls('init_profile')).toHaveLength(0)
  })
})

test.describe('a narrow window', () => {
  test('narrow: the pill on Matches starts the run and, while it goes, leads back to it', async ({ page, world, app }) => {
    await ready(page)
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(760, 800))
    const pill = page.getByRole('main').getByRole('button', { name: /^(Find new jobs|Finding jobs…)$/ })
    await expect(pill).toHaveText('Find new jobs')
    await expect(runButton(page)).toBeHidden()
    world.faults({ claude: { score: { delay_s: 12 } } })
    await pill.click()
    await expect(findingHeading(page)).toBeVisible()
    await expect.poll(() => world.claudeCalls('score').length, { timeout: 60_000 }).toBeGreaterThan(0)
    await nav(page, 'Matches').click()
    await ready(page)
    await expect(pill).toHaveText('Finding jobs…')
    await expect(pill).toBeEnabled()
    await pill.click()
    await expect(findingHeading(page)).toBeVisible()
    await expect(summary(page)).toBeVisible({ timeout: 60_000 })
    expect(world.toolCalls('find_jobs')).toHaveLength(1)
  })
})

test.describe('Needs you', () => {
  test('a home with nothing wrong has no Needs you lines', async ({ page, world }) => {
    await ready(page)
    await expect.poll(() => world.toolCalls('doctor').length, { timeout: 30_000 }).toBeGreaterThan(0)
    await expect(page.getByRole('group', { name: 'Needs you' })).toHaveCount(0)
  })
})
