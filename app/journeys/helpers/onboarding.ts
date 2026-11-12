// The onboarding journeys' own helpers: the wizard's steps reached the way a user reaches them.
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import type { Locator, Page } from '@playwright/test'
import type { World } from '../../test/world/build'
import { expect, type OsStub } from '../fixtures'

/** A first launch may take a while: the server starts, doctor answers. */
export const LAUNCH = { timeout: 60_000 }

export const heading = (page: Page, name: string): Locator => page.getByRole('heading', { name, level: 1 })

export const sourcesHeading = (page: Page) => heading(page, 'Tell me about yourself')
export const readingHeading = (page: Page) => heading(page, 'Reading your CV…')
export const reviewHeading = (page: Page) => heading(page, 'Check your answers')
export const connectHeading = (page: Page) => heading(page, 'Connect Claude')

export const pickButton = (page: Page) => page.getByRole('button', { name: 'Drop relevant documents here (CV or LinkedIn PDF)', exact: true })
export const urlBox = (page: Page) => page.getByLabel('Any relevant URL', { exact: true })
export const chosen = (page: Page) => page.getByRole('list', { name: 'Sources, chosen', exact: true })
export const continueButton = (page: Page) => page.getByRole('button', { name: 'Continue', exact: true })
export const saveAndSearch = (page: Page) => page.getByRole('button', { name: 'Save and start searching', exact: true })
export const saveButton = (page: Page) => page.getByRole('button', { name: 'Save', exact: true })
export const backButton = (page: Page) => page.getByRole('button', { name: 'Back', exact: true })
export const reason = (page: Page) => page.locator('.onb-reason')

/** A file in the world's scratch folder: what the user picks from their disk. */
export function scratchFile(world: World, name: string, content: string | Buffer): string {
  const path = join(world.scratch, name)
  writeFileSync(path, content)
  return path
}

/** The persona's own messy CV, written where the user keeps it. */
export function rawCv(world: World, name = 'cv.txt'): string {
  return scratchFile(world, name, world.persona.rawSource)
}

/** Picks files through the (stubbed) open dialog: the button, then the chips. */
export async function pick(page: Page, os: OsStub, paths: string[] | null): Promise<void> {
  await os.nextOpen(paths)
  await pickButton(page).click()
}

/** Types an address and presses Enter. */
export async function addUrl(page: Page, url: string): Promise<void> {
  await urlBox(page).fill(url)
  await urlBox(page).press('Enter')
}

/** The first launch on Sources, signed in: the persona's CV picked. */
export async function onSourcesWithCv(page: Page, world: World, os: OsStub, name = 'cv.txt'): Promise<string> {
  await expect(sourcesHeading(page)).toBeVisible(LAUNCH)
  const path = rawCv(world, name)
  await pick(page, os, [path])
  await expect(chosen(page).getByText(name, { exact: true })).toBeVisible()
  return path
}

/** From Sources with something chosen, through Reading, to the review. */
export async function readToReview(page: Page): Promise<void> {
  await continueButton(page).click()
  await expect(reviewHeading(page)).toBeVisible(LAUNCH)
}

/** The first launch all the way to the review: the persona's CV, read. */
export async function toReview(page: Page, world: World, os: OsStub): Promise<void> {
  await onSourcesWithCv(page, world, os)
  await readToReview(page)
}

/** One of the four lines of the Reading step, by its words. */
export const readingStep = (page: Page, name: string) =>
  page.getByRole('list', { name: 'Reading', exact: true }).getByRole('listitem').filter({ has: page.getByRole('heading', { name, level: 2 }) })

/** A title's checkbox: its label is the title and the reason. */
export const titleBox = (page: Page, title: string) =>
  page.getByRole('group', { name: 'The job titles to look for' }).getByRole('checkbox', { name: new RegExp(`^${escape(title)}\\b`) })

export const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** The review's fold by its title ("Search", "CV"). */
export const fold = (page: Page, title: string) => page.locator('details').filter({ has: page.locator('summary', { hasText: new RegExp(`^${title}\\b`) }) })

/** The employer sources offered, in order, with whether each is ticked. */
export async function employerSources(page: Page): Promise<{ label: string; on: boolean }[]> {
  const boxes = page.getByRole('group', { name: 'Find employers on' }).getByRole('checkbox')
  const out: { label: string; on: boolean }[] = []
  for (const box of await boxes.all()) {
    out.push({ label: (await box.evaluate((b) => b.closest('label')?.textContent ?? '')).trim(), on: await box.isChecked() })
  }
  return out
}

/** Makes the window narrow, as a phone-width or half-screen window is. */
export async function narrow(app: import('@playwright/test').ElectronApplication, page: Page): Promise<void> {
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(760, 800))
  await expect.poll(() => page.evaluate(() => window.innerWidth)).toBeLessThan(900)
}
