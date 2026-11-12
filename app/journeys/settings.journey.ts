// Settings beyond the connections: Risky sources (profile/config.json keys about how the app works), Your data (the folder, Export and Import), Appearance, Report a problem, and the narrow window.
import { existsSync, readdirSync, readFileSync, realpathSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect } from './fixtures'
import {
  before,
  button,
  dialog,
  exportHome,
  goToMatches,
  goToSettings,
  LAUNCH,
  needsYou,
  openSettings,
  region,
  scrollToTop,
  tarList,
  test,
  zipContents,
} from './helpers/settings'

const theme = (page: import('@playwright/test').Page) => page.evaluate(() => ({ attr: document.documentElement.getAttribute('data-theme'), stored: localStorage.getItem('door.theme') }))

// --------------------------------------------------------------------------- Risky sources

const profileConfig = (world: { home: string }) => JSON.parse(readFileSync(join(world.home, 'profile', 'config.json'), 'utf8'))

test.describe('Risky sources', () => {
  test('offers the sources serving the city; a tick is saved at once', async ({ page, world }) => {
    await openSettings(page)
    const part = region(page, 'Risky sources')
    // Copenhagen: LinkedIn (anywhere), not profession.hu, HelloWork or Jobbsafari
    const linkedin = part.getByRole('checkbox', { name: 'LinkedIn' })
    await expect(linkedin).not.toBeChecked()
    for (const other of ['profession.hu', 'HelloWork', 'Jobbsafari']) await expect(part.getByRole('checkbox', { name: other })).toHaveCount(0)
    await linkedin.check()
    await expect.poll(() => profileConfig(world).linkedin_discovery).toBe(true)
    await linkedin.uncheck()
    await expect.poll(() => profileConfig(world).linkedin_discovery).toBe(false)
  })
})

// --------------------------------------------------------------------------- Appearance

test.describe('Appearance', () => {

  test('Dark turns the whole app dark and stays dark after a reload; Light turns it light', async ({ page, world }) => {
    const config = readFileSync(join(world.home, 'profile', 'config.json'), 'utf8')
    await openSettings(page)
    const look = region(page, 'Appearance')
    await look.getByRole('radio', { name: 'Dark' }).check()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    expect(await theme(page)).toEqual({ attr: 'dark', stored: 'dark' })
    await goToMatches(page)

    await page.reload()
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible(LAUNCH)
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await goToSettings(page)
    await expect(look.getByRole('radio', { name: 'Dark' })).toBeChecked()

    await look.getByRole('radio', { name: 'Light' }).check()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    expect(await theme(page)).toEqual({ attr: 'light', stored: 'light' })
    await goToMatches(page)

    await goToSettings(page)
    await look.getByRole('radio', { name: 'Same as the system' }).check()
    expect(await theme(page)).toEqual({ attr: null, stored: null })
    // a choice for this window, not the profile
    expect(readFileSync(join(world.home, 'profile', 'config.json'), 'utf8')).toBe(config)
  })
})

// --------------------------------------------------------------------------- the page and its parts

test.describe('the Settings page', () => {

  test('Your data says where the data folder is; its path shows it', async ({ page, world, os }) => {
    await openSettings(page)
    const here = region(page, 'Your data')
    await expect(here.getByText(/^Your profile and jobs are stored in/)).toContainText(world.home)
    await here.scrollIntoViewIfNeeded()
    await button(here, world.home).click()
    await expect.poll(async () => (await os.opened()).shown).toEqual([world.home])
    expect((await os.opened()).external).toEqual([])
  })
})

// --------------------------------------------------------------------------- Your data

test.describe('Your data', () => {
  test('Export… writes an archive where the user says, and names it', async ({ page, world, os }) => {
    await openSettings(page)
    const data = region(page, 'Your data')
    const target = join(world.scratch, 'door-export-2026-10-26.tar.gz')
    await os.nextSave(target)
    await button(data, 'Export…').click()
    // the world's home holds compiled PDFs: an export of it is over a megabyte
    await expect(data.getByText(/^Exported \d+ files \(\d\.\d MB\) to door-export-2026-10-26\.tar\.gz\.$/)).toBeVisible()
    await expect(data.getByRole('alert')).toHaveCount(0)
    const files = tarList(target)
    expect(files).toEqual(expect.arrayContaining(['manifest.json', 'profile/config.json', 'profile/cv.md', 'jobs/applications.json']))
    const count = Number((await data.getByText(/^Exported/).textContent())!.match(/Exported (\d+) files/)![1])
    expect(files.filter((f) => !f.endsWith('/') && f !== 'manifest.json')).toHaveLength(count)
    expect(await data.getByText(/^Exported/).textContent()).toContain(`(${(statSync(target).size / 1_000_000).toFixed(1)} MB)`)
    expect(world.toolCalls('export_data').map((c) => c.args)).toEqual([{ path: target }])
  })

  test('Import… asks first; Cancel imports nothing', async ({ page, world, os }) => {
    const archive = exportHome(world, join(world.scratch, 'from-the-laptop.tar.gz'))
    await openSettings(page)
    await os.nextOpen([archive])
    await button(region(page, 'Your data'), 'Import…').click()
    const ask = dialog(page, 'Import from-the-laptop.tar.gz?')
    await expect(ask).toContainText('This replaces your profile and jobs on this computer with the ones in from-the-laptop.tar.gz. What is here now is kept as a backup first, so nothing is lost.')
    await expect(ask).toContainText('If Google Drive is connected, the next sync sends the imported data to Drive')
    await scrollToTop(page)
    await button(ask, 'Cancel').click()
    await expect(ask).toHaveCount(0)
    await os.nextOpen([archive])
    await button(region(page, 'Your data'), 'Import…').click()
    await page.keyboard.press('Escape')
    await expect(ask).toHaveCount(0)
    expect(world.toolCalls('import_data')).toEqual([])
    expect(world.exists('backups')).toBe(false)
  })

  test('Import replaces the data and keeps what was here in backups/', { tag: '@core' }, async ({ page, world, os }) => {
    const archive = exportHome(world, join(world.scratch, 'from-the-laptop.tar.gz'))
    writeFileSync(join(world.home, 'jobs', 'only-on-this-computer.txt'), 'kept in backups\n')
    await openSettings(page)
    await os.nextOpen([archive])
    await button(region(page, 'Your data'), 'Import…').click()
    const readsBefore = world.toolCalls('show_profile').length
    await button(dialog(page, 'Import from-the-laptop.tar.gz?'), 'Import').click()
    const done = region(page, 'Your data').getByText(/^Imported \d+ files\. What was here is kept in .*\/backups\/\d{8}-\d{6}\.$/)
    await expect(done).toBeVisible()
    expect(world.exists('jobs/only-on-this-computer.txt')).toBe(false)
    const backups = readdirSync(join(world.home, 'backups'))
    expect(backups).toHaveLength(1)
    expect(readFileSync(join(world.home, 'backups', backups[0]!, 'jobs', 'only-on-this-computer.txt'), 'utf8')).toBe('kept in backups\n')
    expect(existsSync(join(world.home, 'backups', backups[0]!, 'profile', 'config.json'))).toBe(true)
    expect(world.exists('profile/config.json')).toBe(true)
    // the screens read the new data
    await expect.poll(() => world.toolCalls('show_profile').length).toBeGreaterThan(readsBefore)
  })

  test('Import… of something that is not an export is refused; nothing changes', async ({ page, world, os }) => {
    const junk = join(world.scratch, 'holiday-photos.tar.gz')
    writeFileSync(junk, 'not a gzip file at all')
    await openSettings(page)
    await os.nextOpen([junk])
    await button(region(page, 'Your data'), 'Import…').click()
    await button(dialog(page, 'Import holiday-photos.tar.gz?'), 'Import').click()
    await expect(region(page, 'Your data').getByRole('alert')).toHaveText(/holiday-photos\.tar\.gz is not an export from The other door \(not a \.tar\.gz archive\)$/)
    expect(world.exists('backups')).toBe(false)
    expect(world.exists('profile/config.json')).toBe(true)
  })
})

// --------------------------------------------------------------------------- Report a problem

test.describe('Report a problem', () => {
  test('Save logs… saves an archive with what went wrong, emails and the home folder masked, nothing of the profile', async ({ page, world, os }) => {
    // A failure the screens leave unsaid: doctor answers an error naming the data folder and the persona's email.
    world.faults({ tools: { doctor: { error: `could not read ${world.home}/profile/config.json for ${world.persona.email}`, once: true } } })
    await openSettings(page)
    const report = region(page, 'Report a problem')
    await expect(report).toContainText('No CV, profile, job ads or applications; emails and folder names are hidden.')
    const target = join(world.scratch, 'door-report-2026-10-26.zip')
    await os.nextSave(target)
    await button(report, 'Save logs…').click()
    await expect(report.getByText('Saved as door-report-2026-10-26.zip. Send it to enys.mones@gmail.com.', { exact: true })).toBeVisible()
    await expect(report.getByRole('alert')).toHaveCount(0)
    await report.scrollIntoViewIfNeeded()
    expect(world.toolCalls('report_problem').map((c) => c.args)).toEqual([{ path: target }])

    const files = zipContents(world, target)
    expect(Object.keys(files)).toEqual(expect.arrayContaining(['README.txt', 'about.json', 'doctor.json', 'logs/door.log']))
    expect(Object.keys(files).filter((name) => name.startsWith('runs/')).length).toBeGreaterThan(0)
    expect(Object.keys(files).filter((name) => /^(profile|jobs)\/|cv\.md/.test(name))).toEqual([])
    expect(files['logs/door.log']).toContain('ERROR tool doctor: could not read <data folder>/profile/config.json for <email>')
    expect(JSON.parse(files['about.json']!).version).toBe('0.1.0')
    const all = Object.values(files).join('\n')
    for (const secret of [world.persona.email, world.home, realpathSync(world.home), world.persona.name]) expect(all).not.toContain(secret)
  })

  test('a server that died is in the report, from the app\'s side', async ({ page, world, os }) => {
    world.faults({ tools: { doctor: { crash: true, once: true } } })
    await openSettings(page)
    const target = join(world.scratch, 'after-the-crash.zip')
    await os.nextSave(target)
    await button(region(page, 'Report a problem'), 'Save logs…').click()
    await expect(region(page, 'Report a problem').getByText(/^Saved as after-the-crash\.zip\./)).toBeVisible()
    expect(zipContents(world, target)['logs/door.log']).toMatch(/^\S+Z ERROR app server stopped: /m)
  })
})

// --------------------------------------------------------------------------- the narrow window

test.describe('a narrow window', () => {
  test.use({ worldOptions: { signedIn: false } })

  test('Settings has no side nav and no sidebar lines; Matches says Claude is not signed in on top', async ({ page, app }) => {
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible(LAUNCH)
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.setSize(760, 800))
    await expect.poll(() => page.evaluate(() => window.innerWidth)).toBeLessThan(900)
    await expect(button(page, 'Claude is not signed in')).toBeVisible()
    await goToSettings(page)
    await expect(page.getByRole('navigation', { name: 'Sections' })).toBeHidden()
    await expect(button(page, 'Claude is not signed in')).toHaveCount(0)
    await expect(needsYou(page).getByRole('button')).toHaveCount(0)
    await expect(button(page, 'Find new jobs')).toBeHidden()
    await expect(region(page, 'Your data')).toBeVisible()
  })
})
