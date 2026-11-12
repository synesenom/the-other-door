// Something that keeps going wrong (#593): a failure the next run retries is said nowhere, the same one run
// after run is one line at the sidebar's foot, "Something keeps going wrong. Send a report", that opens
// Settings scrolled to Report a problem; saving a report takes it away. Real runs of door's
// pipeline against the world's boards, a board that fails, scoring that fails. Checklist: inventory/settings.md
// (Report a problem) and inventory/jobs.md §0 (the sidebar's foot).
import { join } from 'node:path'
import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { runButton, runRecords, setBoard } from './helpers/finding'
import { button, needsYou, region } from './helpers/settings'

const LINE = 'Something keeps going wrong. Send a report'

const ready = (page: Page) => expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible({ timeout: 60_000 })
const summary = (page: Page) => page.getByRole('region', { name: 'Run summary' })
const line = (page: Page) => needsYou(page).getByRole('button', { name: LINE, exact: true })

/** Runs `n` times from the sidebar's button, each to its summary. */
async function runs(page: Page, world: Parameters<typeof runRecords>[0], n: number) {
  for (let i = 0; i < n; i++) {
    const before = runRecords(world).length
    await runButton(page).click()
    await expect.poll(() => runRecords(world).length, { timeout: 90_000 }).toBe(before + 1)
    await expect(summary(page)).toBeVisible({ timeout: 90_000 })
    await expect(runButton(page)).toHaveText('Find new jobs')
  }
}

test.describe('something that keeps going wrong', () => {
  test('a board that failed in one run is said nowhere: the next run reads it again', async ({ page, world }) => {
    await ready(page)
    setBoard(world, 'jobindex', { fail: 'jobindex answered 503 Service Unavailable' })
    await runs(page, world, 1)
    expect(world.toolCalls('status_summary').length).toBeGreaterThan(1) // read again after the run
    await expect(page.getByText(LINE)).toHaveCount(0)
  })

  test('a board that failed in each of the last three runs: the line opens Report a problem, and a saved report takes it away', async ({ page, world, os }) => {
    test.setTimeout(300_000)
    await ready(page)
    setBoard(world, 'jobindex', { fail: 'jobindex answered 503 Service Unavailable' })
    await runs(page, world, 2)
    await expect(page.getByText(LINE)).toHaveCount(0)
    await runs(page, world, 1)
    await expect(line(page)).toBeVisible()
    expect(world.readJson('jobs/runs/' + runRecords(world).at(-1)!).failures).toEqual(['jobindex'])

    await line(page).click()
    await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings', exact: true })).toHaveAttribute('aria-current', 'page')
    const report = region(page, 'Report a problem')
    await expect(report).toBeInViewport()
    await expect(button(report, 'Save logs…')).toBeVisible()
    // the runs' end moves with how long they took: masked

    const target = join(world.scratch, 'door-report-2026-10-26.zip')
    await os.nextSave(target)
    await button(report, 'Save logs…').click()
    await expect(report.getByText('Saved as door-report-2026-10-26.zip. Send it to enys.mones@gmail.com.', { exact: true })).toBeVisible()
    await expect(page.getByText(LINE)).toHaveCount(0)
    expect(world.toolCalls('report_problem')).toHaveLength(1)
  })
})
