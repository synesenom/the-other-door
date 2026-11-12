// Moving the data in the built app with a real door server: Export writes an archive where the (stubbed)
// save dialog says; a change made after it is undone by importing that archive, and what was there is
// kept in backups/. Check sites is never clicked (it reaches the real job sites).
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { _electron as electron, expect, test } from '@playwright/test'
import { buildHome } from '../test/home-fixture'

const APP = resolve(__dirname, '..')
const fixture = buildHome()

test.skip(!fixture.hasPython, `no Python at ${fixture.python} (set DOOR_PYTHON)`)

test('exports the data and imports it back, keeping a backup', async () => {
  const archive = join(fixture.scratch, 'moved.tar.gz')
  const config = join(fixture.home, 'profile', 'config.json')
  const original = readFileSync(config, 'utf8')
  const app = await electron.launch({
    args: ['.', ...(process.env.CI ? ['--no-sandbox'] : [])],
    cwd: APP,
    env: { ...(process.env as Record<string, string>), ...fixture.env },
  })
  try {
    // The dialogs are stubbed from here (no production hook).
    await app.evaluate(({ dialog }, path) => {
      dialog.showSaveDialog = (async () => ({ canceled: false, filePath: path })) as unknown as typeof dialog.showSaveDialog
      dialog.showOpenDialog = (async () => ({ canceled: false, filePaths: [path] })) as unknown as typeof dialog.showOpenDialog
    }, archive)
    const page = await app.firstWindow()
    await page.getByRole('button', { name: 'Settings', exact: true }).click({ timeout: 60_000 })
    const data = page.getByRole('region', { name: 'Your data' })
    await data.getByRole('button', { name: 'Export…' }).click()
    await expect(data.getByText(/^Exported \d+ files .* to moved\.tar\.gz\.$/)).toBeVisible({ timeout: 60_000 })
    expect(existsSync(archive)).toBe(true)

    writeFileSync(config, JSON.stringify({ ...JSON.parse(original), name: 'Somebody Else' }))
    await data.getByRole('button', { name: 'Import…' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('moved.tar.gz')
    await dialog.getByRole('button', { name: 'Import' }).click()
    await expect(data.getByText(/^Imported \d+ files\. What was here is kept in /)).toBeVisible({ timeout: 60_000 })
    expect(JSON.parse(readFileSync(config, 'utf8')).name).toBe(JSON.parse(original).name)
    expect(readdirSync(join(fixture.home, 'backups')).length).toBeGreaterThan(0)
  } finally {
    await app.close()
  }
})
