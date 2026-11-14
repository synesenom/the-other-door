// Analytics, Applications (#66): the funnel, each stage against the one before, read from the world's FULL_LEDGER
// through `status_summary` (read only; the Claude usage section is covered by its own tests).
import { expect, test } from './fixtures'
import { ready } from './helpers/applications'
import { argsOf, exists } from './helpers/profile'

test('the funnel follows the ledger', { tag: '@core' }, async ({ page }) => {
  await ready(page)
  await page.getByRole('navigation').getByRole('button', { name: 'Analytics', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Analytics', level: 1 })).toBeVisible()
  const part = page.getByRole('region', { name: 'Applications' })
  await expect(part.getByRole('heading', { name: 'Applications', level: 2 })).toBeVisible()
  // FULL_LEDGER: six jobs were prepared or sent, five sent, three reached an interview, one an offer
  const bar = (name: string) => expect(part.getByRole('img', { name })).toBeVisible()
  await bar('Applied: 5 of 6')
  await bar('Interview: 3 of 5')
  await bar('Offer: 1 of 3')
  await expect(part.getByRole('table')).toHaveCount(0)
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
