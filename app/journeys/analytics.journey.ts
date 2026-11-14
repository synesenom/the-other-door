// Analytics, Applications (#66): the funnel, each stage against the one before, read from the world's FULL_LEDGER
// through `status_summary` (read only; the Claude usage section is covered by its own tests).
import { expect, test } from './fixtures'
import { ready } from './helpers/applications'

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
