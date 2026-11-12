// Applications (inventory/jobs.md §6, and §9 for the narrow window): the board from FULL_LEDGER, a job in
// every column; opening a card, its posting and materials; status changes moving a card.
import { expect, test } from './fixtures'
import { card, column, ledgerEntry, narrow, openCard, pagesLoaded, postingHeading, ready, toApplications } from './helpers/applications'

const KRONVEJ = 'Machine Learning Engineer, MLOps'
const SUNDLINE = 'Senior Data Scientist – Network Optimisation & Demand Forecasting Team'
const PAKKEPOST = 'Senior Data Scientist, Experimentation & Causal Inference'

const name = (...parts: string[]) => new RegExp(`^${parts.map((p) => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s*')}$`)

test('the board: five columns, a job in each, counts and how many are in play', async ({ page, world }) => {
  await toApplications(page)
  await expect(page.getByText('4 in play · 1 in interviews', { exact: true })).toBeVisible()
  const board = page.getByRole('group', { name: 'Applications board' })
  await expect(board.getByRole('heading', { level: 2 })).toHaveText(['Prepared', 'Applied', 'Interviewing', 'Offer', 'Closed'])
  const counts = { Prepared: 1, Applied: 1, Interviewing: 1, Offer: 1, Closed: 2 }
  for (const [heading, n] of Object.entries(counts)) {
    await expect(column(page, heading).getByRole('button')).toHaveCount(n)
    await expect(column(page, heading)).toContainText(`${heading} · ${n}`)
  }
  expect(world.toolCalls('list_matches').map((c) => c.args)).toEqual(expect.arrayContaining([expect.objectContaining({ ongoing: true }), expect.objectContaining({ closed: true })]))
})

test('a prepared card opens its application and comes back through its posting', async ({ page }) => {
  await toApplications(page)
  await openCard(page, KRONVEJ)
  await expect(page.getByRole('button', { name: 'Prepare again', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Not for me' })).toHaveCount(0)
  await page.getByRole('button', { name: 'See the application', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Ready to send', level: 1 })).toBeVisible()
  await expect(page.getByRole('button', { name: '← Applications' })).toHaveCount(0)
  await pagesLoaded(page, 'Letter', 1)
  await page.getByRole('button', { name: '← Posting' }).click()
  await expect(postingHeading(page, KRONVEJ)).toBeVisible()
  await page.getByRole('button', { name: '← Applications' }).click()
  await expect(card(column(page, 'Prepared'), KRONVEJ)).toBeVisible()
})

test('an interview round moves an applied card to Interviewing', { tag: '@core' }, async ({ page, world }) => {
  await toApplications(page)
  await openCard(page, SUNDLINE)
  await page.getByRole('button', { name: 'Status', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: `Status: ${SUNDLINE}` })
  await dialog.getByRole('radio', { name: 'Interview', exact: true }).check()
  await dialog.getByRole('radio', { name: /^Screening/ }).check()
  await dialog.getByRole('button', { name: 'Save' }).click()

  await expect(page.getByRole('status')).toHaveText(`Interview: ${SUNDLINE}. It is in Applications now.`)
  await expect(column(page, 'Applied').getByRole('button')).toHaveCount(0)
  await expect(card(column(page, 'Interviewing'), SUNDLINE)).toHaveAccessibleName(name(SUNDLINE, 'Sundline Shipping', 'one under way: ', 'screening'))
  await expect(page.getByText('4 in play · 2 in interviews', { exact: true })).toBeVisible()
  expect(ledgerEntry(world, 'sundline-network-optimisation')?.status).toBe('interview:screening')
})

test('a rejection ends the last round and moves the card to Closed', async ({ page, world }) => {
  await toApplications(page)
  await openCard(page, PAKKEPOST)
  await page.getByRole('button', { name: 'Status', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: `Status: ${PAKKEPOST}` })
  await dialog.getByRole('radio', { name: 'Rejected', exact: true }).check()
  await dialog.getByRole('button', { name: 'Save' }).click()

  await expect(page.getByRole('status')).toHaveText(`Rejected: ${PAKKEPOST}.`)
  await expect(column(page, 'Interviewing').getByRole('button')).toHaveCount(0)
  await expect(card(column(page, 'Closed'), PAKKEPOST)).toHaveAccessibleName(name(PAKKEPOST, 'Pakkepost Norden', 'rejected'))
  await expect(page.getByText('3 in play', { exact: true })).toBeVisible()
  expect(ledgerEntry(world, 'pakkepost-causal-experimentation')?.status).toBe('rejected')
})

test('Not for me on a prepared job, through Status, closes it as withdrawn', async ({ page, world }) => {
  await toApplications(page)
  await openCard(page, KRONVEJ)
  await page.getByRole('button', { name: 'Status', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: `Status: ${KRONVEJ}` })
  await dialog.getByRole('radio', { name: 'Not for me', exact: true }).check()
  await expect(dialog.getByRole('button', { name: 'Save' })).toBeDisabled()
  await dialog.getByLabel('Why not?').fill('They want someone on site five days a week.')
  await dialog.getByRole('button', { name: 'Save' }).click()

  await expect(page.getByRole('status')).toHaveText(`Not for me: ${KRONVEJ}.`)
  await expect(column(page, 'Prepared').getByRole('button')).toHaveCount(0)
  await expect(card(column(page, 'Closed'), KRONVEJ)).toHaveAccessibleName(name(KRONVEJ, 'Kronvej', 'withdrawn'))
  // newest first
  await expect(column(page, 'Closed').getByRole('button').first()).toHaveAccessibleName(new RegExp(`^${KRONVEJ}`))
  const entry = ledgerEntry(world, KRONVEJ_KEY)!
  expect(entry.status).toBe('discarded')
  expect(entry.history.at(-1)).toMatchObject({ status: 'discarded', notes: 'They want someone on site five days a week.' })
})

const KRONVEJ_KEY = 'kronvej-ml-engineer-mlops'

test('Not yet applied takes a job off the board and back to Matches', async ({ page, world }) => {
  await toApplications(page)
  await openCard(page, KRONVEJ)
  await page.getByRole('button', { name: 'Status', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: `Status: ${KRONVEJ}` })
  await dialog.getByRole('radio', { name: 'Not yet applied', exact: true }).check()
  await dialog.getByRole('button', { name: 'Save' }).click()

  await expect(page.getByRole('status')).toHaveText('Back in Matches.')
  await expect(card(page, KRONVEJ)).toHaveCount(0)
  await expect(page.getByText('3 in play · 1 in interviews', { exact: true })).toBeVisible()
  expect(ledgerEntry(world, KRONVEJ_KEY)?.status).toBe('unapplied')

  await page.getByRole('navigation').getByRole('button', { name: 'Matches', exact: true }).click()
  await expect(page.getByRole('button', { name: new RegExp(`^(New since your last review )?${KRONVEJ.replace(/[,]/g, '.')}`) })).toBeVisible()
})

test('a board that cannot load shows the error, and loads on the next visit', async ({ page, world }) => {
  await ready(page)
  world.faults({ tools: { list_matches: { error: 'applications.json is not valid JSON' } } })
  await page.getByRole('navigation').getByRole('button', { name: 'Applications', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveText('applications.json is not valid JSON')
  await expect(page.getByRole('group', { name: 'Applications board' })).toHaveCount(0)

  world.clearFaults()
  await page.getByRole('navigation').getByRole('button', { name: 'Matches', exact: true }).click()
  await page.getByRole('navigation').getByRole('button', { name: 'Applications', exact: true }).click()
  await expect(page.getByRole('group', { name: 'Applications board' })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('narrow: Ready to send saves the shown document and has I’ve applied in the bar', async ({ app, page, world, os }) => {
  await ready(page)
  await narrow(app, page)
  await page.getByRole('navigation').getByRole('button', { name: 'Applications', exact: true }).click()
  await openCard(page, KRONVEJ)
  await page.getByRole('button', { name: 'See the application', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Ready to send', level: 1 })).toBeVisible()
  await pagesLoaded(page, 'Letter', 1)
  await expect(page.getByRole('button', { name: /^Save / })).toHaveText(['Save letter'])
  await expect(page.getByRole('button', { name: "I've applied" })).toHaveCount(1)

  await page.getByRole('button', { name: 'CV · 2 pages' }).click()
  await expect(page.getByRole('button', { name: /^Save / })).toHaveText(['Save CV'])
  const { mkdirSync } = await import('node:fs')
  const { join } = await import('node:path')
  mkdirSync(join(world.scratch, 'saved'), { recursive: true })
  await os.nextSave(join(world.scratch, 'saved', 'cv.pdf'))
  await page.getByRole('button', { name: 'Save CV' }).click()
  await expect(page.getByRole('status')).toHaveText('Saved as cv.pdf in saved.')

  await page.getByRole('button', { name: "I've applied" }).click()
  await expect(page.getByRole('status')).toHaveText(`Applied: ${KRONVEJ}. It is in Applications now.`)
  expect(ledgerEntry(world, KRONVEJ_KEY)?.status).toBe('applied')
})
