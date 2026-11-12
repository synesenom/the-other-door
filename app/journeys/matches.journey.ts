// Matches: the list, New only, the new dots and count, opening a posting (mark_seen), the pushed view with its
// stepper and keys; the shell around it (nav, notification clicks). Checklist: inventory/jobs.md §0 and §2.
import { expect, test } from './fixtures'
import {
  holdRun,
  matchesLoaded,
  matchRows,
  METTE_NEW,
  METTE_ORDER,
  notificationOpens,
  openRow,
  postingHeading,
  row,
  seenOnDisk,
  shownTitle,
} from './helpers/matches'

const back = (page: import('@playwright/test').Page) => page.getByRole('button', { name: '← Matches' })
const stepper = (page: import('@playwright/test').Page) => page.getByRole('group', { name: 'Previous and next match' })
const nav = (page: import('@playwright/test').Page, name: string) => page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name, exact: true })

test.describe('the list', () => {
  test('lists the matches best first, each with its title, English title, company, place and score', async ({ page, world }) => {
    await matchesLoaded(page)
    const names = await matchRows(page).getByRole('button').allInnerTexts()
    METTE_ORDER.forEach((key, i) => expect(names[i]).toContain(world.ads[key].title))
    const fjord = world.ads['fjordpension-senior-ds']
    await expect(row(page, world, 'fjordpension-senior-ds')).toHaveAccessibleName(
      new RegExp(`^${fjord.title}\\s*${fjord.titleEn}\\s*Fjordpension · Copenhagen\\s*0\\.84$`),
    )
    // a new match: its dot is named first
    await expect(row(page, world, 'baltic-power-lead-ds')).toHaveAccessibleName(/^New since your last review\s*Lead Data Scientist, Energy Trading\s*Baltic Power Trading ApS · Copenhagen \(hybrid\)\s*0\.94$/)
    await expect(page.getByRole('img', { name: 'New since your last review' })).toHaveCount(3)
    for (const key of METTE_NEW) await expect(row(page, world, key).getByRole('img', { name: 'New since your last review' })).toBeVisible()
    await expect(page.getByRole('switch', { name: 'New only' })).toHaveAttribute('aria-checked', 'false')
    await expect(nav(page, 'Matches')).toHaveAttribute('aria-current', 'page')
    await expect(page.getByText('Last run Oct 25, 02:41 PM')).toBeVisible()
    expect(world.toolCalls('list_matches')[0].args).toMatchObject({ new_only: false, ongoing: false, closed: false })
    expect(world.toolCalls('mark_seen')).toEqual([])
  })

  test('New only lists only the new matches, and off again lists them all, with no call', async ({ page, world }) => {
    await matchesLoaded(page)
    const lists = world.toolCalls('list_matches').length
    await page.getByRole('switch', { name: 'New only' }).click()
    await expect(page.getByRole('switch', { name: 'New only' })).toHaveAttribute('aria-checked', 'true')
    await expect(matchRows(page)).toHaveCount(3)
    for (const key of METTE_NEW) await expect(row(page, world, key)).toBeVisible()
    await page.getByRole('switch', { name: 'New only' }).click()
    await expect(matchRows(page)).toHaveCount(METTE_ORDER.length)
    expect(world.toolCalls('list_matches')).toHaveLength(lists)
  })

  test('New only with every new match seen says there is nothing new, not that nothing was scored', async ({ page, world }) => {
    await matchesLoaded(page)
    for (const key of METTE_NEW) {
      await openRow(page, world, key)
      await back(page).click()
    }
    await expect(page.getByRole('img', { name: 'New since your last review' })).toHaveCount(0)
    await expect.poll(() => seenOnDisk(world).length).toBe(3)
    await page.getByRole('switch', { name: 'New only' }).click()
    await expect(matchRows(page)).toHaveCount(0)
    await expect(page.getByText(/^Nothing scored yet/)).toHaveCount(0)
    await expect(page.getByText(/nothing new/i).last()).toBeVisible()
  })

  test('a list that cannot be read says why, and reads again once it can', async ({ page, world }) => {
    await matchesLoaded(page)
    world.faults({ tools: { list_matches: { error: "profile/config.json is invalid: min_score: Input should be less than or equal to 1" } } })
    await nav(page, 'Settings').click()
    await nav(page, 'Matches').click()
    await expect(page.getByRole('alert')).toHaveText('profile/config.json is invalid: min_score: Input should be less than or equal to 1')
    await expect(matchRows(page)).toHaveCount(0)
    await expect(page.getByText(/^Nothing scored yet/)).toHaveCount(0)
    await expect(page.getByRole('status').filter({ hasText: 'Loading…' })).toHaveCount(0)
    world.clearFaults()
    await nav(page, 'Settings').click()
    await nav(page, 'Matches').click()
    await expect(matchRows(page)).toHaveCount(METTE_ORDER.length)
    await expect(page.getByRole('alert')).toHaveCount(0)
  })
})

test.describe('opening a match', () => {
  test('opens it full width, marks it seen, and back keeps the row marked', { tag: '@core' }, async ({ page, world }) => {
    await matchesLoaded(page)
    const id = world.jobId('vestvind-senior-ds-forecasting')
    await openRow(page, world, 'vestvind-senior-ds-forecasting')
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toHaveCount(0)
    await expect(back(page)).toHaveAttribute('title', 'Esc')
    await expect(stepper(page)).toContainText('2 of 9')
    await expect.poll(() => seenOnDisk(world)).toEqual([id])
    expect(world.toolCalls('mark_seen').map((c) => c.args)).toEqual([{ job_id: id }])
    expect(world.toolCalls('show').at(-1)?.args).toMatchObject({ job_id: id })
    await back(page).click()
    await expect(page.getByRole('img', { name: 'New since your last review' })).toHaveCount(2)
    await expect(row(page, world, 'vestvind-senior-ds-forecasting')).toHaveAttribute('aria-current', 'true')
    await expect(row(page, world, 'vestvind-senior-ds-forecasting').getByRole('img')).toHaveCount(0)
    await expect(row(page, world, 'baltic-power-lead-ds')).toHaveAttribute('aria-current', 'false')
    // a match that was not new is opened without mark_seen
    await openRow(page, world, 'nordisk-elnet-prognose')
    await back(page).click()
    expect(world.toolCalls('mark_seen')).toHaveLength(1)
  })

  test('a match opened while another process runs is recorded as seen once the run ends', async ({ page, world }) => {
    await matchesLoaded(page)
    const id = world.jobId('baltic-power-lead-ds')
    const run = await holdRun(world)
    try {
      await expect(page.getByRole('heading', { name: 'Finding jobs', level: 1 })).toBeVisible()
      await nav(page, 'Matches').click()
      await openRow(page, world, 'baltic-power-lead-ds')
      await expect.poll(() => world.toolCalls('mark_seen').length).toBe(1)
      await back(page).click()
      await expect(page.getByRole('img', { name: 'New since your last review' })).toHaveCount(2)
      expect(seenOnDisk(world)).toEqual([])
    } finally {
      await run.release()
    }
    // the run ended: the window reloads Matches; the match stays seen, and is recorded
    await expect.poll(() => world.toolCalls('list_matches').length, { timeout: 15_000 }).toBeGreaterThan(2)
    await expect(page.getByRole('img', { name: 'New since your last review' })).toHaveCount(2, { timeout: 5_000 })
    await expect.poll(() => seenOnDisk(world), { timeout: 5_000 }).toEqual([id])
  })

  test('the list keeps its scroll position when a posting deep in it closes', async ({ app, page, world }) => {
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(1200, 600))
    await matchesLoaded(page)
    const last = row(page, world, 'egeskov-kommune-prognoser')
    await last.scrollIntoViewIfNeeded()
    await expect(row(page, world, 'baltic-power-lead-ds')).not.toBeInViewport()
    await last.click()
    await expect(postingHeading(page, world, 'egeskov-kommune-prognoser')).toBeVisible()
    await back(page).click()
    await expect(last).toBeInViewport()
    await expect(row(page, world, 'baltic-power-lead-ds')).not.toBeInViewport()
  })
})

test.describe('stepping through the matches', () => {
  test('Next and Previous step through the list, and stop at its ends', async ({ page, world }) => {
    await matchesLoaded(page)
    await openRow(page, world, 'baltic-power-lead-ds')
    await expect(stepper(page)).toContainText('1 of 9')
    const prev = page.getByRole('button', { name: 'Previous match' })
    const next = page.getByRole('button', { name: 'Next match' })
    await expect(prev).toBeDisabled()
    await expect(prev).toHaveAttribute('title', 'Previous match (k)')
    await expect(next).toHaveAttribute('title', 'Next match (j)')
    await next.click()
    await expect(postingHeading(page, world, 'vestvind-senior-ds-forecasting')).toBeVisible()
    await expect(stepper(page)).toContainText('2 of 9')
    // stepping onto a new match makes it seen
    await expect.poll(() => seenOnDisk(world).length).toBe(2)
    await prev.click()
    await expect(postingHeading(page, world, 'baltic-power-lead-ds')).toBeVisible()
    for (let i = 1; i < METTE_ORDER.length; i++) await next.click()
    await expect(postingHeading(page, world, 'egeskov-kommune-prognoser')).toBeVisible()
    await expect(stepper(page)).toContainText('9 of 9')
    await expect(next).toBeDisabled()
    await expect(prev).toBeEnabled()
    await back(page).click()
    await expect(row(page, world, 'egeskov-kommune-prognoser')).toHaveAttribute('aria-current', 'true')
  })

  test('j pressed on a dialog’s button leaves the posting behind it alone', async ({ page, world }) => {
    await matchesLoaded(page)
    await openRow(page, world, 'nordisk-elnet-prognose')
    await page.getByRole('button', { name: 'Status', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: `Status: ${shownTitle(world, 'nordisk-elnet-prognose')}` })
    await dialog.getByRole('button', { name: 'Cancel' }).focus()
    await page.keyboard.press('j')
    await expect(dialog).toBeVisible()
    await expect(postingHeading(page, world, 'nordisk-elnet-prognose')).toBeVisible()
  })

  test('Esc on the score’s hint closes the hint and stays on the posting', async ({ page, world }) => {
    await matchesLoaded(page)
    await openRow(page, world, 'nordisk-elnet-prognose')
    await page.getByRole('button', { name: 'Why this score' }).focus()
    await expect(page.getByRole('tooltip')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('tooltip')).toHaveCount(0)
    await expect(postingHeading(page, world, 'nordisk-elnet-prognose')).toBeVisible()
  })
})

test.describe('the shell', () => {
  test('the nav goes to Applications and back to Matches, which reads the list again', async ({ page, world }) => {
    await matchesLoaded(page)
    const before = world.toolCalls('list_matches').length
    await nav(page, 'Applications').click()
    await expect(page.getByRole('heading', { name: 'Applications', level: 1 })).toBeVisible()
    await expect(nav(page, 'Applications')).toHaveAttribute('aria-current', 'page')
    await expect(nav(page, 'Matches')).not.toHaveAttribute('aria-current', 'page')
    await nav(page, 'Matches').click()
    await matchesLoaded(page)
    await expect(nav(page, 'Matches')).toHaveAttribute('aria-current', 'page')
    expect(world.toolCalls('list_matches').filter((c) => !c.args?.ongoing && !c.args?.closed).length).toBeGreaterThan(before)
  })
})

test.describe('notification clicks', () => {
  test('"New jobs found" opens Matches on New only', async ({ app, page }) => {
    await matchesLoaded(page)
    await nav(page, 'Settings').click()
    await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible()
    await notificationOpens(app, { screen: 'matches', newOnly: true })
    await expect(page.getByRole('switch', { name: 'New only' })).toHaveAttribute('aria-checked', 'true')
    await expect(matchRows(page)).toHaveCount(3)
    await expect(nav(page, 'Matches')).toHaveAttribute('aria-current', 'page')
    // without newOnly: all of them
    await notificationOpens(app, { screen: 'matches' })
    await expect(page.getByRole('switch', { name: 'New only' })).toHaveAttribute('aria-checked', 'false')
    await expect(matchRows(page)).toHaveCount(METTE_ORDER.length)
  })

  test('"Application ready" opens the materials on the document it names', async ({ app, page, world }) => {
    await matchesLoaded(page)
    await notificationOpens(app, { screen: 'materials', jobId: world.jobId('kronvej-ml-engineer-mlops'), inPlay: true, document: 'cv' })
    await expect(page.getByRole('heading', { name: 'Ready to send', level: 1 })).toBeVisible()
    await expect(page.getByRole('button', { name: /^CV · / })).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByRole('button', { name: /^Letter · / })).toHaveAttribute('aria-pressed', 'false')
  })
})
