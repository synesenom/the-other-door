// Analytics, Applications (#66, #87): the interview rate and the two split bars, read from the world's FULL_LEDGER
// through `status_summary` (read only; the Claude usage section is covered by its own tests).
import { expect, test } from './fixtures'
import { ready } from './helpers/applications'

test('the applications follow the ledger', { tag: '@core' }, async ({ page }) => {
  await ready(page)
  await page.getByRole('navigation').getByRole('button', { name: 'Analytics', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Analytics', level: 1 })).toBeVisible()
  const part = page.getByRole('region', { name: 'Applications' })
  await expect(part.getByRole('heading', { name: 'Applications', level: 2 })).toBeVisible()
  // FULL_LEDGER: five sent (an offer, one interviewing, one waiting, two rejected or ghosted); three of the four with an outcome led to an interview
  await expect(part).toContainText('75%of your applications with an outcome (an interview, a rejection or no reply) led to an interview: 3 of 4, likely between 50% and 90%.')
  const bar = (group: string, name: string) => expect(part.getByRole('group', { name: group }).getByRole('img', { name })).toBeVisible()
  await bar('Your matches', 'Applied 5, Prepared, not sent 1, Not yet 9')
  await bar('Your applications', 'Offer 1, Interviewing 1, Waiting for an answer 1, Rejected or ghosted 2')
})
