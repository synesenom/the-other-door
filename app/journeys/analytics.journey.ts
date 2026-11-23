// Analytics, Applications (#66, #87): the interview rate, read from the world's FULL_LEDGER
// through `status_summary` (read only); Claude usage (#67) after a find in the world; Market (#65).
import { expect, test } from './fixtures'
import { ready } from './helpers/applications'
import { argsOf, exists } from './helpers/profile'

test('the interview rate follows the ledger', { tag: '@core' }, async ({ page }) => {
  await ready(page)
  await page.getByRole('navigation').getByRole('button', { name: 'Analytics', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Analytics', level: 1 })).toBeVisible()
  const part = page.getByRole('region', { name: 'Applications' })
  await expect(part.getByRole('heading', { name: 'Applications', level: 2 })).toBeVisible()
  // FULL_LEDGER: five sent (an offer, one interviewing, one waiting, two rejected or ghosted); three of the four with an outcome led to an interview
  await expect(part).toContainText('75%of your applications with an outcome (an interview, a rejection or no reply) led to an interview: 3 of 4.')
  await expect(part.getByRole('img')).toHaveCount(0) // where each stands is the Applications board's columns
})

// Claude usage (#64, #67): the world's stand-in claude prices each answer (`COST_USD` in test/world/claude.py:
// a scoring chunk $0.02, a title translation $0.01, anything else $0.03), so a find leaves a usage log to read.
test('Claude usage: nothing before the first search, then what the search cost', { tag: '@core' }, async ({ page, world }) => {
  await ready(page)
  // Market's grouping call runs beside the summary's read as Analytics opens: failed here, it costs nothing,
  // whichever comes first (Market lists the names as written)
  world.faults({ claude: { market: { fail: 'not now' } } })
  const nav = page.getByRole('navigation')
  await nav.getByRole('button', { name: 'Analytics', exact: true }).click()
  const usage = page.getByRole('region', { name: 'Claude usage' })
  await expect(usage).toContainText("What Claude's work costs shows here after your first search.")
  await expect(page.getByRole('region', { name: 'Market' }).getByRole('listitem').first()).toBeVisible({ timeout: 60_000 })
  world.clearFaults()

  await page.getByRole('complementary').getByRole('button', { name: 'Find new jobs', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Run summary' })).toBeVisible({ timeout: 90_000 })

  // Market groups the run's new skill names with one more call as Analytics opens; once it is done, the
  // usage log is settled and the next opening reads all of it.
  await nav.getByRole('button', { name: 'Analytics', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Market' }).getByRole('listitem').first()).toBeVisible({ timeout: 60_000 })
  await nav.getByRole('button', { name: 'Matches', exact: true }).click()
  await nav.getByRole('button', { name: 'Analytics', exact: true }).click()

  // the find: one scoring chunk and one title translation; everything else: the one reading of the CV before scoring ($0.01, cached
  // after it) and Market's grouping after the run
  expect(world.claudeCalls('score')).toHaveLength(1)
  expect(world.claudeCalls('translate')).toHaveLength(1)
  expect(world.claudeCalls('cv_read')).toHaveLength(1)
  expect(world.claudeCalls('market')).toHaveLength(2) // the failed one, then the one that answered
  await expect(usage.getByText(/^≈ \$/)).toHaveText('≈ $0.05')
  await expect(usage).toContainText("You don't pay this. Your Claude plan covers it. The last 7 days, estimated at API prices.")
  await expect(usage.getByText(/^About /)).toHaveText('About $0.03 a search, $1.00 an application') // no prepare yet: an application is sized from scoring one posting
  await expect(usage.getByRole('img')).toHaveAttribute('aria-label', 'Finding jobs 60%, Everything else 40%')
  const finding = usage.locator('.usage-activity').filter({ hasText: 'Finding jobs' })
  await expect(finding.locator('h3')).toHaveText('Finding jobs · 3 postings scored')
  await expect(finding.locator('.usage-row').first()).toContainText('$0.03')
  await expect(finding.getByRole('listitem')).toHaveCount(0) // no row per feature: lines of money the user does not pay
  await expect(usage.locator('.usage-activity').filter({ hasText: 'Everything else' }).locator('h3')).toHaveText('Everything else · 2 other requests')
})

const openAnalytics = async (page: Parameters<typeof ready>[0]) => {
  await ready(page)
  await page.getByRole('navigation').getByRole('button', { name: 'Analytics', exact: true }).click()
  return page.getByRole('region', { name: 'Market' })
}

test.describe('Market (#65)', () => {
  test('counts the ads when Analytics opens, once, and writes no report', async ({ page, world }) => {
    const market = await openAnalytics(page)
    await expect(market.getByRole('listitem', { name: 'Python, in your CV', exact: true })).toHaveText('Python · 86% of the ads', { timeout: 60_000 })
    expect(argsOf(world, 'market')).toEqual([expect.objectContaining({ save: false })])
    expect(world.toolCalls('market')).toHaveLength(1)
    expect(exists(world, 'jobs/market')).toBe(false)
  })

  test('a report that failed is said nowhere and Market is left out (principle 9)', async ({ page, world }) => {
    await ready(page)
    world.faults({ tools: { market: { error: 'profile/companies.json: invalid JSON — Expecting value', once: true } } })
    await page.getByRole('navigation').getByRole('button', { name: 'Analytics', exact: true }).click()
    await expect.poll(() => world.toolCalls('market').length, { timeout: 60_000 }).toBe(1)
    await expect(page.getByRole('region', { name: 'Market' })).toHaveCount(0)
    await expect(page.getByRole('main').getByText('Market', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('alert')).toHaveCount(0)
  })
})
