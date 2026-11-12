// Helpers of the Prepare and Applications journeys (prepare.journey.ts, applications.journey.ts).
import type { ElectronApplication, Locator, Page } from '@playwright/test'
import { expect } from '../fixtures'
import type { World } from '../../test/world/build'

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** The app is up: Matches has listed the world's matches. */
export async function ready(page: Page): Promise<void> {
  await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByRole('list').first().getByRole('listitem').first()).toBeVisible()
}

/** The heading of an open posting. */
export const postingHeading = (page: Page, title: string): Locator => page.getByRole('heading', { name: title, level: 2, exact: true })

/** Opens a match from the Matches list by its (original) title. */
export async function openMatch(page: Page, title: string): Promise<void> {
  await ready(page)
  await page.getByRole('button', { name: new RegExp(`^(New since your last review )?${escape(title)}`) }).click()
  await expect(postingHeading(page, title)).toBeVisible()
}

/** Goes to Applications from the sidebar and waits for the board. */
export async function toApplications(page: Page): Promise<void> {
  await ready(page)
  await page.getByRole('navigation').getByRole('button', { name: 'Applications', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Applications', level: 1 })).toBeVisible()
  await expect(page.getByRole('group', { name: 'Applications board' })).toBeVisible()
}

/** A column of the board (a region named by its heading). */
export const column = (page: Page, heading: string): Locator => page.getByRole('region', { name: heading, exact: true })

/** A card on the board, by the start of its accessible name (the title the board shows). */
export const card = (scope: Page | Locator, title: string): Locator => scope.getByRole('button', { name: new RegExp(`^${escape(title)}`) })

/** Opens a card of the board and waits for its posting. */
export async function openCard(page: Page, boardTitle: string, postingTitle = boardTitle): Promise<void> {
  await card(page, boardTitle).click()
  await expect(postingHeading(page, postingTitle)).toBeVisible()
}

/** The page images shown: exactly `count`, each decoded with a width (a broken image has none). */
export async function pagesLoaded(page: Page, alt: 'CV' | 'Letter', count: number): Promise<void> {
  const images = page.getByRole('img', { name: new RegExp(`^${alt}, page \\d+$`) })
  await expect(images).toHaveCount(count)
  for (let i = 0; i < count; i++) {
    await expect(images.nth(i)).toHaveAttribute('alt', `${alt}, page ${i + 1}`)
    await expect
      .poll(() =>
        images.nth(i).evaluate(async (el) => {
          const img = el as HTMLImageElement
          try {
            await img.decode()
          } catch {
            return 0
          }
          return img.naturalWidth
        }),
      )
      .toBeGreaterThan(0)
  }
}

/** The job's ledger entry, or undefined. */
export function ledgerEntry(world: World, key: string): { status: string; history: { status: string; notes?: string }[]; materials?: Record<string, string> } | undefined {
  return world.readJson('jobs/applications.json')[world.jobId(key)]
}

/** A narrow window (the phone layout, under 900 px). */
export async function narrow(app: ElectronApplication, page: Page): Promise<void> {
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.setSize(760, 800))
  await expect.poll(() => page.evaluate(() => window.matchMedia('(max-width: 899px)').matches)).toBe(true)
}

/** A letter of `words` words on one page. */
export function letterTex(words: number): string {
  const body = Array.from({ length: words }, () => 'forecasting').join(' ')
  return ['\\documentclass{letter}', '\\begin{document}', '', body, '', '\\end{document}', ''].join('\n')
}
