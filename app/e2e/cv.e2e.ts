// The CV in the built app with a real door server: an edit is saved to the temp home's cv.md with the
// previous one kept as cv.md.bak. The real claude, profile/ and jobs/ are never touched.
import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { _electron as electron, expect, test } from '@playwright/test'
import { buildHome } from '../test/home-fixture'

const APP = resolve(__dirname, '..')
const fixture = buildHome()

test.skip(!fixture.hasPython, `no Python at ${fixture.python} (set DOOR_PYTHON)`)

test('edits and saves the CV', async () => {
  const cvPath = join(fixture.home, 'profile', 'cv.md')
  const before = readFileSync(cvPath, 'utf8')
  const app = await electron.launch({
    args: ['.', ...(process.env.CI ? ['--no-sandbox'] : [])],
    cwd: APP,
    env: { ...(process.env as Record<string, string>), ...fixture.env },
  })
  try {
    const page = await app.firstWindow()
    await page.getByRole('button', { name: 'Profile', exact: true }).click({ timeout: 60_000 })
    await page.getByRole('button', { name: 'CV', exact: true }).click()
    const editor = page.getByLabel('Your CV (Markdown)')
    await expect(editor).toHaveValue(before, { timeout: 30_000 })
    await editor.press('End')
    await editor.pressSequentially('\nAlso: SQL.\n')
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('Saved. The previous version is kept as cv.md.bak.')).toBeVisible({ timeout: 30_000 })
    expect(readFileSync(cvPath, 'utf8')).toContain('Also: SQL.')
    expect(readFileSync(`${cvPath}.bak`, 'utf8')).toBe(before)
  } finally {
    await app.close()
  }
})
