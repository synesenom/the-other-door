// Profile → CV's Style: the default style and the one built from a CV of the user's, side by side. A CV is chosen,
// a build runs in the background, the new style waits to be compared and is chosen, the prepared CVs are printed
// again (never the sent ones), and the way back. The stand-in print lays text out, so the look itself is not
// seen: the journey checks the previews load, the two config keys, and which files were printed again.
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { argsOf, config, exists, openCv } from './helpers/profile'
import { scratchFile } from './helpers/onboarding'

const STYLED_PDF = resolve(__dirname, '..', '..', 'tests', 'tailoring', 'fixtures', 'styles', 'latex-classic.pdf')
const readyLine = (page: Page) => page.getByRole('button', { name: 'Your CV style is ready to compare', exact: true })
const sheet = (page: Page, name: string) => page.getByRole('img', { name })
const loaded = (page: Page, name: string) => expect.poll(() => sheet(page, name).evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0)

// A short CV (the stand-in print sets it on one page, as the build's stress renders need), one application prepared
// and one sent.
test.use({
  worldOptions: {
    persona: 'jonas',
    ledger: {
      'ostjysk-forsyning-miljoingenior': { status: 'prepared', materials: true },
      'midtvand-projektingenior': { status: 'applied', materials: true, history: [{ status: 'prepared', daysAgo: 4 }] },
    },
  },
})

// The build runs in a process of its own, and the sidebar reads its state every 30 s.
test.setTimeout(300_000)

test('compare the default with a style built from a CV: build, choose it, print the prepared CVs again, go back', async ({ page, world, os }) => {
  await openCv(page)
  await expect(sheet(page, "The other door's, first page")).toBeVisible({ timeout: 90_000 })
  await loaded(page, "The other door's, first page")
  await expect(page.getByText('In use', { exact: true })).toBeVisible()
  expect(config(world).cv_template ?? null).toBeNull()

  // a CV chosen in the dialog: the build starts, the sheet of the default stays
  await os.nextOpen([scratchFile(world, 'my-cv.pdf', readFileSync(STYLED_PDF))])
  await page.getByRole('button', { name: 'Use the style of my CV…' }).click()
  await expect(page.getByText('Building your style…')).toBeVisible()
  expect(world.toolCalls('build_style')).toHaveLength(1)
  expect(argsOf(world, 'build_style')[0]!['file']).toMatch(/my-cv\.pdf$/)

  // ready: the two side by side, and the sidebar says so
  await expect(page.getByRole('button', { name: 'Use this style', exact: true })).toBeVisible({ timeout: 240_000 })
  await expect(readyLine(page)).toBeVisible()
  await loaded(page, 'Like your CV, first page')
  expect(exists(world, 'profile/style.next/cv.template.html')).toBe(true)
  expect(exists(world, 'profile/style/cv.template.html')).toBe(false)
  expect(config(world).cv_template ?? null).toBeNull() // nothing in use changed by building

  // the full pages open in a dialog to read
  await page.getByRole('button', { name: 'Show Like your CV in full' }).click()
  const dialog = page.getByRole('dialog', { name: 'Like your CV' })
  await expect(dialog.getByRole('img').first()).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)

  // choose it
  const out = join(world.home, 'jobs', 'output')
  const book = world.readJson<Record<string, { status: string }>>('jobs/applications.json')
  const prepared = Object.keys(book).find((id) => book[id]!.status === 'prepared')!
  const sent = Object.keys(book).find((id) => book[id]!.status === 'applied')!
  const printed = (id: string, file = 'cv.pdf') => statSync(join(out, id, file)).mtimeMs
  const before = { prepared: printed(prepared), sent: printed(sent), sentCopy: printed(sent, 'sent/cv.pdf') }
  await page.getByRole('button', { name: 'Use this style', exact: true }).click()
  await expect(readyLine(page)).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Print 1 prepared CV again in the new style' })).toBeVisible()
  expect(config(world).cv_template).toBe('profile/style/cv.template.html')
  expect(config(world).cover_letter_template).toBe('profile/style/cover-letter.template.html')
  expect(exists(world, 'profile/style/cv.template.html')).toBe(true)
  expect(exists(world, 'profile/style.next')).toBe(false)
  expect(printed(prepared)).toBe(before.prepared) // not printed again until asked

  await page.getByRole('button', { name: 'Print 1 prepared CV again in the new style' }).click()
  await expect(page.getByText('1 printed again.')).toBeVisible({ timeout: 120_000 })
  expect(argsOf(world, 'use_style').map((a) => a['rerender'] ?? false)).toEqual([false, true])
  expect(printed(prepared)).toBeGreaterThan(before.prepared)
  expect(printed(sent)).toBe(before.sent) // an application already sent is never touched
  expect(printed(sent, 'sent/cv.pdf')).toBe(before.sentCopy)
  expect(readdirSync(join(out, sent, 'sent')).length).toBeGreaterThan(0)

  // the way back: The other door's again, the built style kept
  await page.getByRole('button', { name: "Use The other door's" }).click()
  await expect(page.getByRole('button', { name: "Use my CV's style" })).toBeVisible()
  expect(config(world).cv_template).toBeNull()
  expect(config(world).cover_letter_template).toBeNull()
  expect(exists(world, 'profile/style/cv.template.html')).toBe(true)
})
