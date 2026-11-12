
import { expect, test } from './fixtures'
import {
  addUrl,
  chosen,
  continueButton,
  LAUNCH,
  pick,
  rawCv,
  readingHeading,
  scratchFile,
  sourcesHeading,
  urlBox,
} from './helpers/onboarding'

test.use({ worldOptions: { empty: true } })

const LINKEDIN = "LinkedIn pages can't be read; save your profile as a PDF (More → Save to PDF) and add that file."

test('an address typed as the only source, then Continue clicked, is read', async ({ page, world }) => {
  await expect(sourcesHeading(page)).toBeVisible(LAUNCH)
  await urlBox(page).fill('https://mettekl.example.com')
  await continueButton(page).click({ force: true, timeout: 5_000 })
  await expect(readingHeading(page)).toBeVisible({ timeout: 5_000 })
  await expect.poll(() => world.toolCalls('draft_cv').length).toBe(1)
})

test('sources with files and pages, ready to read', async ({ page, world, os }) => {
  await expect(sourcesHeading(page)).toBeVisible(LAUNCH)
  await pick(page, os, [rawCv(world, 'Mette Kjær Larsen – CV.txt'), scratchFile(world, 'LinkedIn profile.md', world.persona.cv)])
  await addUrl(page, 'https://mettekl.example.com')
  await addUrl(page, 'https://github.example.com/mkl')
  await expect(chosen(page).getByRole('listitem')).toHaveCount(4)
})

test('a LinkedIn address written with a trailing dot is refused in the box too', async ({ page }) => {
  await expect(sourcesHeading(page)).toBeVisible(LAUNCH)
  await addUrl(page, 'https://linkedin.com./in/mette')
  await expect(page.getByRole('alert')).toHaveText(LINKEDIN, { timeout: 5_000 })
  await expect(chosen(page)).toHaveCount(0)
})
