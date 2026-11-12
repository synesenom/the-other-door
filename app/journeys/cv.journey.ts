// Profile → CV: the editor of profile/cv.md (load, edit, preview, Save with cv.md.bak, Undo), the CV's
// notes (no CV, gaps), and what happens to unsaved text. The pages above the editor are
// cv-tools.journey.ts.
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from './fixtures'
import { cvBox, exists, openCv, readText, saveButton, started, writeText } from './helpers/profile'

test.describe('the editor', () => {
  test('opens on the CV as saved, with no note', async ({ page, world }) => {
    await openCv(page)
    const parts = page.getByRole('group', { name: 'Part of the profile' })
    await expect(parts.getByRole('button', { name: 'CV', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await expect(cvBox(page)).toHaveValue(world.persona.cv)
    await expect(page.getByRole('note')).toHaveCount(0)
    await expect(page.getByRole('switch', { name: 'Preview' })).toHaveAttribute('aria-checked', 'false')
    await expect(saveButton(page)).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Undo changes' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Add a page' })).toBeEnabled()
    // the extras are off for now (CvEditor's `extras`)
    await expect(page.getByRole('button', { name: 'What should I learn?' })).toHaveCount(0)
    expect(world.toolCalls('market')).toEqual([])
  })

  test('Save writes cv.md and keeps the previous one as cv.md.bak', { tag: '@core' }, async ({ page, world }) => {
    writeText(world, 'profile/cv.draft.md', '# A draft from the wizard\n') // a draft left over is done with
    await openCv(page)
    await cvBox(page).fill(`${world.persona.cv}\n- Danish driving licence B\n`)
    await expect(page.getByText('Unsaved changes', { exact: true })).toBeVisible()
    await expect(page.getByText('Save or undo your changes before adding from a page.')).toBeVisible()
    await saveButton(page).click()
    await expect(page.getByText('Saved. The previous version is kept as cv.md.bak.')).toBeVisible()
    expect(readText(world, 'profile/cv.md')).toBe(`${world.persona.cv}\n- Danish driving licence B\n`)
    expect(readText(world, 'profile/cv.md.bak')).toBe(world.persona.cv)
    expect(world.toolCalls('save_cv')).toHaveLength(1)
    expect(exists(world, 'profile/cv.draft.md')).toBe(false)
    await expect(saveButton(page)).toBeDisabled()
    await expect(page.getByText('Save or undo your changes before adding from a page.')).toHaveCount(0)
    // typing again clears the message
    await cvBox(page).press('x')
    await expect(page.getByText('Saved. The previous version is kept as cv.md.bak.')).toHaveCount(0)
  })

  test('a failing save says why and keeps the text', async ({ page, world }) => {
    await openCv(page)
    world.faults({ tools: { save_cv: { error: 'profile/cv.md is read-only' } } })
    await cvBox(page).fill('# Mette\n')
    await saveButton(page).click()
    await expect(page.getByRole('alert')).toHaveText('profile/cv.md is read-only')
    await expect(cvBox(page)).toHaveValue('# Mette\n')
    expect(readText(world, 'profile/cv.md')).toBe(world.persona.cv)
    world.clearFaults()
    await saveButton(page).click()
    await expect(page.getByText('Saved. The previous version is kept as cv.md.bak.')).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
    expect(readText(world, 'profile/cv.md')).toBe('# Mette\n')
  })

  test('unsaved CV text survives a look at the details', async ({ page }) => {
    await openCv(page)
    await cvBox(page).fill('# Mette, rewritten\n')
    await page.getByRole('group', { name: 'Part of the profile' }).getByRole('button', { name: 'Details', exact: true }).click()
    await page.getByRole('group', { name: 'Part of the profile' }).getByRole('button', { name: 'CV', exact: true }).click()
    await expect(cvBox(page)).toHaveValue('# Mette, rewritten\n', { timeout: 5_000 })
  })

  test('a cv.md that cannot be read as text is said, not shown as an empty CV', async ({ page, world }) => {
    writeFileSync(join(world.home, 'profile', 'cv.md'), Buffer.from([0xff, 0xfe, 0x00, 0x41, 0xc3, 0x28]))
    await openCv(page)
    await expect(page.getByRole('note').or(page.getByRole('alert'))).toBeVisible({ timeout: 5_000 })
  })
})

test.describe('a CV with gaps (Jonas: TODO where the draft found nothing)', () => {
  test.use({ worldOptions: { persona: 'jonas' } })

  test('the preview marks each gap to fill in', async ({ page }) => {
    await openCv(page)
    await page.getByRole('switch', { name: 'Preview' }).click()
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
    await expect(page.getByRole('note')).toHaveText('You have no CV yet. Write it here, or Draft it from your CV file or pages')
    await expect(cvBox(page)).toHaveValue('')
    await expect(saveButton(page)).toBeDisabled()
    expect(exists(world, 'profile/cv.md')).toBe(false)
  })

  test('the first save does not speak of a backup', async ({ page, world }) => {
    await openCv(page)
    await cvBox(page).fill(world.persona.cv)
    await saveButton(page).click()
    await expect(page.getByText(/^Saved\./)).toBeVisible()
    await expect(page.getByText(/cv\.md\.bak/)).toHaveCount(0, { timeout: 3_000 })
  })

  test('the sidebar line goes once the first CV is saved', async ({ page, world }) => {
    await openCv(page)
    await expect(page.getByRole('group', { name: 'Needs you' }).getByRole('button', { name: 'You have no CV yet' })).toBeVisible()
    await cvBox(page).fill(world.persona.cv)
    await saveButton(page).click()
    await expect(page.getByText(/^Saved\./)).toBeVisible()
    await expect(page.getByRole('group', { name: 'Needs you' }).getByRole('button', { name: 'You have no CV yet' })).toHaveCount(0, { timeout: 5_000 })
  })
})
