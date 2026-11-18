// Profile → Master CV: the editor of profile/cv.md (load, edit, preview, the live save with cv.md.bak), the CV's
// notes (no CV, gaps). The file and the pages above the editor are cv-tools.journey.ts.
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from './fixtures'
import { cvBox, editCv, exists, openCv, readText, saveButton, started, writeText } from './helpers/profile'
import type { Page } from '@playwright/test'

/** The quiet line beside Preview once the text is written. */
const written = (page: Page) => page.getByRole('status').getByText('Saved', { exact: true })

test.describe('the editor', () => {
  test('opens on the CV as saved, as it reads; Edit shows its text', async ({ page, world }) => {
    await openCv(page)
    await expect(page.getByRole('region', { name: 'Master CV' }).getByRole('heading', { name: 'Skills' })).toBeVisible()
    await expect(cvBox(page)).toHaveCount(0)
    await expect(page.getByRole('note')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Add a page' })).toBeEnabled()
    await page.getByRole('button', { name: 'Edit the Master CV' }).click()
    await expect(cvBox(page)).toHaveValue(world.persona.cv)
  })

  test('the text saves itself; cv.md.bak keeps the CV as it was when Profile opened', { tag: '@core' }, async ({ page, world }) => {
    writeText(world, 'profile/cv.draft.md', '# A draft from the wizard\n') // a draft left over is done with
    await editCv(page)
    await cvBox(page).fill(`${world.persona.cv}\n- Danish driving licence B\n`)
    await expect(written(page)).toBeVisible({ timeout: 5_000 })
    expect(readText(world, 'profile/cv.md')).toBe(`${world.persona.cv}\n- Danish driving licence B\n`)
    expect(readText(world, 'profile/cv.md.bak')).toBe(world.persona.cv)
    expect(exists(world, 'profile/cv.draft.md')).toBe(false)
    // a second edit: written, the backup still the CV of the visit's start
    await cvBox(page).press('End')
    await cvBox(page).pressSequentially('- Forklift')
    await cvBox(page).blur()
    await expect.poll(() => readText(world, 'profile/cv.md')).toBe(`${world.persona.cv}\n- Danish driving licence B\n- Forklift`)
    expect(readText(world, 'profile/cv.md.bak')).toBe(world.persona.cv)
    // the details' Save has nothing to do with it
    await expect(saveButton(page)).toBeDisabled()
  })

  test('a failing save says why, keeps the text, and is tried again', async ({ page, world }) => {
    await editCv(page)
    world.faults({ tools: { save_cv: { error: 'profile/cv.md is read-only' } } })
    await cvBox(page).fill('# Mette\n')
    await cvBox(page).blur()
    await expect(page.getByRole('alert')).toHaveText('profile/cv.md is read-only')
    await expect(cvBox(page)).toHaveValue('# Mette\n')
    expect(readText(world, 'profile/cv.md')).toBe(world.persona.cv)
    world.clearFaults()
    await cvBox(page).fill('# Mette\n\n')
    await cvBox(page).blur()
    await expect(page.getByRole('alert')).toHaveCount(0)
    await expect.poll(() => readText(world, 'profile/cv.md')).toBe('# Mette\n\n')
  })

  test('a cv.md that cannot be read as text is said, not shown as an empty CV', async ({ page, world }) => {
    writeFileSync(join(world.home, 'profile', 'cv.md'), Buffer.from([0xff, 0xfe, 0x00, 0x41, 0xc3, 0x28]))
    await openCv(page)
    await expect(page.getByRole('note').or(page.getByRole('alert'))).toBeVisible({ timeout: 5_000 })
  })
})

test.describe('a CV with gaps (Jonas: TODO where the draft found nothing)', () => {
  test.use({ worldOptions: { persona: 'jonas' } })

  test('the CV as it reads marks each gap to fill in', async ({ page }) => {
    await openCv(page)
    await expect(page.getByRole('button', { name: 'to fill in' })).toHaveCount(3, { timeout: 5_000 })
    await page.getByRole('button', { name: 'to fill in' }).first().click()
    await expect(cvBox(page)).toBeFocused()
    expect(await cvBox(page).evaluate((b: HTMLTextAreaElement) => b.value.slice(b.selectionStart, b.selectionEnd))).toBe('TODO')
  })
})

test.describe('no CV yet', () => {
  test.use({ worldOptions: { noCv: true } })

  test('Draft it from your CV file or pages opens the set-up wizard', async ({ page }) => {
    await openCv(page)
    await page.getByRole('note').getByRole('button', { name: 'Draft it from your CV file or pages' }).click()
    await expect(page.getByRole('heading', { name: 'Tell me about yourself' })).toBeVisible()
  })

  test('the sidebar line opens the CV, which says there is none', async ({ page, world }) => {
    await started(page)
    await page.getByRole('group', { name: 'Needs you' }).getByRole('button', { name: 'You have no CV yet' }).click()
    await expect(page.getByRole('note')).toHaveText('You have no CV yet. Choose your CV file, write it below, or Draft it from your CV file or pages')
    await expect(cvBox(page)).toHaveValue('')
    expect(exists(world, 'profile/cv.md')).toBe(false)
  })

  test('the first CV saves itself, with no backup, and the sidebar line goes', async ({ page, world }) => {
    await openCv(page)
    await expect(page.getByRole('group', { name: 'Needs you' }).getByRole('button', { name: 'You have no CV yet' })).toBeVisible()
    await cvBox(page).fill(world.persona.cv)
    await expect(written(page)).toBeVisible({ timeout: 5_000 })
    expect(exists(world, 'profile/cv.md.bak')).toBe(false)
    await expect(page.getByRole('group', { name: 'Needs you' }).getByRole('button', { name: 'You have no CV yet' })).toHaveCount(0, { timeout: 5_000 })
  })
})
