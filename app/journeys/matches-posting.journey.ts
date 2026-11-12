// The posting opened from Matches (what it shows, the ad opened in the browser), and Matches in a narrow
// window. Its other branches are Posting.test.tsx's. Checklist: inventory/jobs.md §3 and §9.
import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { matchesLoaded, narrowWindow, openRow } from './helpers/matches'

const article = (page: Page) => page.getByRole('article')
/** The posting's text buttons, in order (the score's hint is an icon). */
const actions = (page: Page) => article(page).getByRole('button').filter({ hasText: /\S/ })

test.describe('what the posting shows', () => {
  test('a Danish ad: its title in English, where and when, the score, why it fits, the gaps, its language and text', async ({ page, world }) => {
    const ad = world.ads['fjordpension-senior-ds']
    await matchesLoaded(page)
    await openRow(page, world, 'fjordpension-senior-ds')
    await expect(article(page).getByText(ad.titleEn!, { exact: true })).toBeVisible()
    await expect(article(page).getByText('Fjordpension · Copenhagen · posted Oct 20 · via Jobindex', { exact: true })).toBeVisible()
    await expect(article(page).getByText('0.84', { exact: true })).toBeVisible()
    await expect(page.getByRole('list', { name: 'Why it fits' }).getByRole('listitem')).toHaveText(ad.matching)
    await expect(page.getByRole('list', { name: 'Gaps' }).getByRole('listitem')).toHaveText(ad.missing)
    // Mette speaks Danish: the language is named, nothing asked of her
    await expect(article(page).getByText('Danish', { exact: true })).toBeVisible()
    await expect(article(page).getByText(ad.description.slice(0, 60))).toBeVisible()
    await expect(actions(page)).toHaveText(['Prepare application', 'Apply on job.fjordpension.example', 'Status', 'Not for me'])
    expect(world.toolCalls('show').map((c) => c.args?.job_id)).toContain(world.jobId('fjordpension-senior-ds'))
  })
})

test.describe('opening the ad', () => {
  test('a separate application page: "Apply on <host>" opens it in the browser', async ({ page, world, os }) => {
    await matchesLoaded(page)
    await openRow(page, world, 'baltic-power-lead-ds')
    await expect(page.getByRole('button', { name: 'Open in browser' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Apply on careers.balticpower.example' }).click()
    await expect.poll(async () => (await os.opened()).external).toEqual([world.ads['baltic-power-lead-ds'].applyUrl])
  })
})

test.describe('a narrow window', () => {
  test('Matches has its own "Find new jobs", and the sidebar keeps only the tabs', async ({ app, page, world }) => {
    await matchesLoaded(page)
    await narrowWindow(app, page)
    await expect(page.getByRole('main').getByRole('button', { name: 'Find new jobs' })).toBeVisible()
    await expect(page.getByRole('complementary').getByRole('button', { name: 'Find new jobs' })).toBeHidden()
    await expect(page.getByText(/^Last run/)).toBeHidden()
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
  })
})
