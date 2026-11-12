// Profile's journeys: getting to Details or the CV, the save bar, and the files of the world's home they read.
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import type { ElectronApplication, Locator, Page } from '@playwright/test'
import { expect } from '../fixtures'
import { repoRoot, type World } from '../../test/world/build'

/** The window is up (the first screen has its heading): the server answered at least once. */
export async function started(page: Page): Promise<void> {
  await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Profile', exact: true })).toBeVisible({ timeout: 60_000 })
}

/** Profile → Details, loaded (its first section is on screen). */
export async function openDetails(page: Page): Promise<void> {
  await started(page)
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Profile', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Profile', level: 1 })).toBeVisible()
  await expect(page.getByRole('region', { name: 'About you' })).toBeVisible({ timeout: 30_000 })
}

/** Profile → CV, loaded (the editor is on screen). */
export async function openCv(page: Page): Promise<void> {
  await openDetails(page)
  await page.getByRole('group', { name: 'Part of the profile' }).getByRole('button', { name: 'CV', exact: true }).click()
  await expect(page.getByRole('switch', { name: 'Preview' })).toBeVisible({ timeout: 30_000 })
}

/** The editor's textarea. */
export const cvBox = (page: Page): Locator => page.getByRole('textbox', { name: 'Your CV (Markdown)' })

/** The save bar's Save (Details and CV each have one; never two on screen). */
export const saveButton = (page: Page): Locator => page.getByRole('button', { name: 'Save', exact: true })

/** A chip list's input: type, then Enter. */
export async function addChip(page: Page, label: string, value: string): Promise<void> {
  const box = page.getByRole('textbox', { name: label, exact: true })
  await box.fill(value)
  await box.press('Enter')
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** A chip input shows exactly these chips, in this order (each chip is its text and its × button). */
export async function expectChips(page: Page, label: string, values: string[]): Promise<void> {
  const list = page.getByRole('list', { name: `${label}, chosen`, exact: true })
  if (values.length === 0) return expect(list).toHaveCount(0)
  await expect(list.getByRole('listitem')).toHaveText(values.map((v) => new RegExp(`^${escape(v)}\\s*×?$`)))
}

export const homeFile = (world: World, rel: string) => join(world.home, rel)
export const readText = (world: World, rel: string): string => readFileSync(homeFile(world, rel), 'utf8')
export const writeText = (world: World, rel: string, text: string): void => writeFileSync(homeFile(world, rel), text)
export const exists = (world: World, rel: string): boolean => existsSync(homeFile(world, rel))

/** profile/config.json as it is now. */
export const config = (world: World): Record<string, any> => world.readJson('profile/config.json')

/** The example CV of the checkout, byte for byte. */
export function exampleCv(): string {
  return readFileSync(join(repoRoot, 'profile.example', 'cv.md'), 'utf8')
}

/** profile/companies.json's entries. */
export const companies = (world: World): any[] => world.readJson('profile/companies.json').companies

/** Rewrites profile/companies.json with these entries (the list reads it when Profile opens). */
export function writeCompanies(world: World, entries: any[]): void {
  writeText(world, 'profile/companies.json', JSON.stringify({ version: 1, companies: entries }, null, 2))
}

/** One companies.json entry, followed on a feed unless said otherwise. */
export function company(name: string, over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    name,
    feed: { platform: 'greenhouse', id: name.toLowerCase().replace(/[^a-z0-9]+/g, '-') },
    aliases: [],
    status: 'followed',
    reason: null,
    found_via: 'linkedin',
    evidence: 'a board that lists open jobs',
    first_seen: '2026-09-01T09:00:00+00:00',
    last_checked: '2026-10-25T09:00:00+00:00',
    last_relevant: '2026-10-24T09:00:00+00:00',
    ...over,
  }
}

/** The window at a phone-like width (under the 900 px where the sidebar becomes a tab bar). */
export async function narrow(app: ElectronApplication): Promise<void> {
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.setSize(760, 800))
}

/** The arguments of each call of a tool, in order. */
/** The arguments the window sent each call of a tool, in order (the server's own defaults, logged as null, left out). */
export const argsOf = (world: World, tool: string): Record<string, unknown>[] =>
  world.toolCalls(tool).map((c) => Object.fromEntries(Object.entries(c.args ?? {}).filter(([, v]) => v !== null)))
