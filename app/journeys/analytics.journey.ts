// Analytics, Applications (#66, #87): the interview rate and where each application stands, read from the world's FULL_LEDGER
// through `status_summary` (read only; the Claude usage section is covered by its own tests).
import { expect, test } from './fixtures'
import { ready } from './helpers/applications'
import { argsOf, exists } from './helpers/profile'

test('the applications follow the ledger', { tag: '@core' }, async ({ page }) => {
  await ready(page)
  await page.getByRole('navigation').getByRole('button', { name: 'Analytics', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Analytics', level: 1 })).toBeVisible()
  const part = page.getByRole('region', { name: 'Applications' })
  await expect(part.getByRole('heading', { name: 'Applications', level: 2 })).toBeVisible()
  // FULL_LEDGER: five sent (an offer, one interviewing, one waiting, two rejected or ghosted); three of the four with an outcome led to an interview
  await expect(part).toContainText('75%of your applications with an outcome (an interview, a rejection or no reply) led to an interview: 3 of 4, likely between 50% and 90%.')
  await expect(part.getByRole('group', { name: 'Your applications' }).getByRole('img', { name: 'Offer 1, Interviewing 1, Waiting for an answer 1, Rejected or no answer 2' })).toBeVisible()
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

  test('a report that failed says why', async ({ page, world }) => {
    await ready(page)
    world.faults({ tools: { market: { error: 'profile/companies.json: invalid JSON — Expecting value', once: true } } })
    await page.getByRole('navigation').getByRole('button', { name: 'Analytics', exact: true }).click()
    const market = page.getByRole('region', { name: 'Market' })
    await expect(market.getByRole('alert')).toBeVisible({ timeout: 60_000 })
  })
})
