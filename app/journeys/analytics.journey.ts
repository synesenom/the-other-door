// Analytics, Applications (#66): the funnel and how each stage went, read from the world's FULL_LEDGER
// through `status_summary` (read only; the Claude usage section is covered by its own tests).
import { expect, test } from './fixtures'
import { ready } from './helpers/applications'

test('the funnel and the stage table follow the ledger', async ({ page }) => {
  await ready(page)
  await page.getByRole('navigation').getByRole('button', { name: 'Analytics', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Analytics', level: 1 })).toBeVisible()
  const part = page.getByRole('region', { name: 'Applications' })
  await expect(part.getByRole('heading', { name: 'Applications', level: 2 })).toBeVisible()
  // FULL_LEDGER: six jobs were prepared or sent, five sent, three reached an interview, one an offer
  const row = (label: string) => part.locator('.funnel-row', { hasText: label })
  await expect(row('Prepared')).toHaveText(/6$/)
  await expect(row('Applied')).toHaveText(/5$/)
  await expect(row('Interview')).toHaveText(/3$/)
  await expect(row('Offer')).toHaveText(/1$/)
  const application = part.getByRole('row', { name: /^Application/ })
  await expect(application).toContainText('passed')
  await expect(application).toContainText('%')
})
