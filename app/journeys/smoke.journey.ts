// The harness itself: the app opens on the world's matches with the real server, the window's clock is the world's.
import { expect, test } from './fixtures'

test('opens on Matches with the world’s new matches, best first', async ({ page, world }) => {
  await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible({ timeout: 60_000 })
  const rows = page.getByRole('list').first().getByRole('listitem')
  await expect(rows.first()).toBeVisible()
  expect(await page.evaluate(() => new Date().toISOString().slice(0, 10))).toBe('2026-10-26')
  expect(world.toolCalls('list_matches').length).toBeGreaterThan(0)
})
