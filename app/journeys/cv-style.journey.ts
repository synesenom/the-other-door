// Profile → CV's Style: the default style and the one built from the user's CV file, side by side. The CV file is
// chosen under Sources, the switch "Use my own style" builds the style from it in the background and puts it in use
// once ready, the prepared CVs are printed again (never the sent ones), and the switch goes back. The stand-in print
// lays text out, so the look itself is not seen: the journey checks the previews load, the two config keys, and
// which files were printed again.
import { readFileSync, readdirSync, rmSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { argsOf, config, exists, openCv } from './helpers/profile'
import { scratchFile } from './helpers/onboarding'

const STYLED_PDF = resolve(__dirname, '..', '..', 'tests', 'style', 'fixtures', 'styles', 'latex-classic.pdf')
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

const ownStyle = (page: Page) => page.getByRole('switch', { name: 'Use my own style' })

/** The CV file under Sources: chosen in the dialog and read for what it adds (nothing kept here), which the app remembers. */
async function chooseCvFile(page: Page, world: Parameters<typeof scratchFile>[0], os: { nextOpen(files: string[]): Promise<void> }) {
  await os.nextOpen([scratchFile(world, 'my-cv.pdf', readFileSync(STYLED_PDF))])
  await page.getByRole('button', { name: /^(Add a CV file|Replace CV file)…$/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Add from your CV file' })
  await expect(dialog.getByRole('button', { name: /^(Cancel|Close)$/ })).toBeVisible({ timeout: 120_000 })
  await dialog.getByRole('button', { name: /^(Cancel|Close)$/ }).click()
  await expect(page.getByRole('group', { name: 'Sources' }).getByText('my-cv.pdf', { exact: true })).toBeVisible()
}

test('the switch builds the style from the CV file and uses it once ready, prints the prepared CVs again, and goes back', async ({ page, world, os }) => {
  await openCv(page)
  await expect(sheet(page, 'The other door, first page')).toBeVisible({ timeout: 90_000 })
  await loaded(page, 'The other door, first page')
  await expect(ownStyle(page)).toHaveAttribute('aria-checked', 'false')
  expect(config(world).cv_template ?? null).toBeNull()

  await chooseCvFile(page, world, os)
  await ownStyle(page).click()
  await expect(page.getByText(/^Building your style/)).toBeVisible()
  expect(world.toolCalls('build_style')).toHaveLength(1)
  expect(argsOf(world, 'build_style')[0]!['file']).toMatch(/my-cv\.pdf$/)

  // ready: put in use at once (the switch asked for it), the two side by side
  const out = join(world.home, 'jobs', 'output')
  const book = world.readJson<Record<string, { status: string }>>('jobs/applications.json')
  const prepared = Object.keys(book).find((id) => book[id]!.status === 'prepared')!
  const sent = Object.keys(book).find((id) => book[id]!.status === 'applied')!
  const printed = (id: string, file = 'cv.pdf') => statSync(join(out, id, file)).mtimeMs
  const before = { prepared: printed(prepared), sent: printed(sent), sentCopy: printed(sent, 'sent/cv.pdf') }
  await expect(page.getByRole('button', { name: 'Print 1 prepared CV again' })).toBeVisible({ timeout: 240_000 })
  await expect(readyLine(page)).toHaveCount(0)
  await loaded(page, 'Your CV, first page')
  await expect(ownStyle(page)).toHaveAttribute('aria-checked', 'true')
  // the content column scrolls, never the window (a stray absolutely placed node once grew it)
  expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight)).toBe(true)
  expect(config(world).cv_template).toBe('profile/style/cv.template.html')
  expect(config(world).cover_letter_template).toBe('profile/style/cover-letter.template.html')
  expect(exists(world, 'profile/style/cv.template.html')).toBe(true)
  expect(exists(world, 'profile/style.next')).toBe(false)
  expect(printed(prepared)).toBe(before.prepared) // not printed again until asked

  // the full pages open in a dialog to read
  await page.getByRole('button', { name: 'Show Your CV in full' }).click()
  const dialog = page.getByRole('dialog', { name: 'Your CV' })
  await expect(dialog.getByRole('img').first()).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)

  await page.getByRole('button', { name: 'Print 1 prepared CV again' }).click()
  await expect(page.getByText('1 printed again.')).toBeVisible({ timeout: 120_000 })
  expect(argsOf(world, 'use_style').map((a) => a['rerender'] ?? false)).toEqual([false, true])
  expect(printed(prepared)).toBeGreaterThan(before.prepared)
  expect(printed(sent)).toBe(before.sent) // an application already sent is never touched
  expect(printed(sent, 'sent/cv.pdf')).toBe(before.sentCopy)
  expect(readdirSync(join(out, sent, 'sent')).length).toBeGreaterThan(0)

  // the way back: the switch off, The other door's style again, the built style kept
  await ownStyle(page).click()
  await expect(ownStyle(page)).toHaveAttribute('aria-checked', 'false')
  await expect.poll(() => config(world).cv_template ?? null).toBeNull()
  expect(config(world).cover_letter_template ?? null).toBeNull()
  expect(exists(world, 'profile/style/cv.template.html')).toBe(true)
})

test('a CV file whose structure the model could not read is refused in words and no build starts', async ({ page, world, os }) => {
  await openCv(page)
  await expect(sheet(page, 'The other door, first page')).toBeVisible({ timeout: 90_000 })
  await chooseCvFile(page, world, os)
  world.faults({ claude: { structure: { fail: 'Claude usage limit reached' } } })
  rmSync(join(world.home, '.style', 'structure'), { recursive: true, force: true }) // a cached read would answer without the model
  await ownStyle(page).click()
  await expect(page.getByRole('alert')).toContainText("Claude could not be reached, or Claude's usage limit is reached")
  await expect(page.getByText(/^Building your style/)).toHaveCount(0)
  await expect(ownStyle(page)).toHaveAttribute('aria-checked', 'false')
  expect(exists(world, 'profile/style.next/cv.template.html')).toBe(false)
})
