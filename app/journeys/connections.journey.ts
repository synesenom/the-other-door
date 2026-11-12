// Settings → Connections: Claude (signed in, signed out, the sign-in with a wrong and a right code, use another
// account, its install and the failures you can act on), Google Drive over the world's folder (it syncs by
// itself: on connecting, on opening the app (push, pull, a conflict, a failure), before disconnecting; the
// sidebar's "Google Drive sync failed" and "Google Drive needs a choice"),
// and the phone against the pretend tunnel. The rarer branches are the unit tests' (inventory/settings.md).
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { createHash } from 'node:crypto'
import { expect } from './fixtures'
import {
  before,
  button,
  claudeRow,
  dialog,
  driveArchive,
  driveRow,
  driveState,
  exportHome,
  fingerprint,
  goToSettings,
  LAUNCH,
  needsYou,
  openSettings,
  patchDriveState,
  phoneRow,
  phoneScans,
  readDriveState,
  standInCurl,
  tarList,
  test,
} from './helpers/settings'

const md5 = (path: string) => createHash('md5').update(readFileSync(path)).digest('hex')
/** sync_data as the app's own syncs send it: neither side chosen. */
const NO_CHOICE = { keep_local: false, keep_drive: false }
const loginArgs = (dir: string) => readFileSync(join(dir, 'claude-login-args'), 'utf8')

// --------------------------------------------------------------------------- Claude

test.describe('Claude, signed in', () => {
  test('Settings shows who is signed in and the plan, with Use another account', async ({ page, world }) => {
    await openSettings(page)
    const row = claudeRow(page)
    await expect(row).toContainText(`Signed in as ${world.persona.email} (Max)`)
    await expect(button(row, 'Check again')).toHaveCount(0)
    await expect(button(row, 'Use another account')).toBeVisible()
    await expect(button(row, 'Sign in with Claude')).toHaveCount(0)
    await expect(needsYou(page).getByRole('button')).toHaveCount(0)
  })

  test('Use another account opens the sign-in under the row, and a right code keeps it signed in', async ({ page, world }) => {
    await openSettings(page)
    const row = claudeRow(page)
    await button(row, 'Use another account').click()
    await expect(button(row, 'Use another account')).toHaveCount(0)
    await button(row, 'Sign in with Claude').click()
    await button(row, 'The page showed a code?').click()
    await row.getByLabel('Sign-in code').fill('world-code#ok')
    await button(row, 'Send code').click()
    await expect(row).toContainText(`Signed in as ${world.persona.email} (Max)`)
    // Right: once doctor confirms the sign-in, the block is done with; no spinner is left behind.
    await expect(row.getByText('Checking the sign-in…')).toHaveCount(0, { timeout: 10_000 })
  })
})

test.describe('Claude, signed out', () => {
  test.use({ worldOptions: { signedIn: false } })

  test('the sidebar line opens Settings, where the row says Claude is not signed in', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible(LAUNCH)
    await button(needsYou(page), 'Claude is not signed in').click()
    await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible()
    const row = claudeRow(page)
    await expect(row).toContainText('Not signed in. The other door needs your Claude plan to score jobs and write applications.')
    await expect(button(row, 'Sign in with Claude')).toBeVisible()
    await expect(button(row, 'Use another account')).toHaveCount(0)
  })

  test('Sign in with Claude waits for the browser, with the profile’s email on claude’s page', async ({ page, world, os }) => {
    await openSettings(page)
    const row = claudeRow(page)
    await button(row, 'Sign in with Claude').click()
    await expect(row.getByText('Finish signing in in your browser. The other door waits here.')).toBeVisible()
    await expect(button(row, 'Open the sign-in page again')).toBeEnabled()
    await expect(button(row, 'Cancel')).toBeVisible()
    expect(loginArgs(world.dir)).toBe(`auth login --claudeai --email ${world.persona.email}`)
    // claude's own page is never opened by the app until asked
    expect((await os.opened()).external).toEqual([])
    await button(row, 'Open the sign-in page again').click()
    await expect.poll(async () => (await os.opened()).external).toEqual(['https://claude.com/cai/oauth/authorize?code=true&state=world'])
    expect(existsSync(join(world.dir, 'claude-signed-in'))).toBe(false)
  })

  test('a wrong code fails the sign-in; Try again with the right one signs in and clears the sidebar line', { tag: '@core' }, async ({ page, world }) => {
    await openSettings(page)
    const row = claudeRow(page)
    await expect(button(needsYou(page), 'Claude is not signed in')).toBeVisible()
    await button(row, 'Sign in with Claude').click()
    await button(row, 'The page showed a code?').click()
    await row.getByLabel('Sign-in code').fill('world-code#wrong')
    await row.getByLabel('Sign-in code').press('Enter')
    await expect(row.getByRole('alert')).toHaveText("The sign-in didn't go through: Request failed with status code 400")
    await expect(button(row, 'Try again')).toBeVisible()
    expect(existsSync(join(world.dir, 'claude-signed-in'))).toBe(false)

    await button(row, 'Try again').click()
    await button(row, 'The page showed a code?').click()
    await row.getByLabel('Sign-in code').fill('world-code#ok')
    await button(row, 'Send code').click()
    await expect(row).toContainText(`Signed in as ${world.persona.email} (Max)`)
    await expect(button(needsYou(page), 'Claude is not signed in')).toHaveCount(0)
    expect(existsSync(join(world.dir, 'claude-signed-in'))).toBe(true)
  })

  test('claude says the sign-in worked but doctor cannot see it: the block says so instead of checking forever', async ({ page, world }) => {
    await openSettings(page)
    world.faults({ claude: { login: { stay_signed_out: true } } })
    const row = claudeRow(page)
    await button(row, 'Sign in with Claude').click()
    await button(row, 'The page showed a code?').click()
    await row.getByLabel('Sign-in code').fill('world-code#ok')
    await button(row, 'Send code').click()
    await expect(row.getByRole('alert')).toHaveText("claude said the sign-in worked, but The other door still can't see the sign-in.", { timeout: 15_000 })
  })
})

test.describe('Claude, not installed', () => {
  test.use({ worldOptions: { noClaude: true }, seed: before((world) => standInCurl(world)) })

  test('the installer failing says why (its own error), and the row stays Not installed', async ({ page, world }) => {
    standInCurl(world, 'fail')
    await openSettings(page)
    const row = claudeRow(page)
    await button(row, 'Install').click()
    await button(dialog(page, 'Install the Claude command line?'), 'Install the Claude command line').click()
    await expect(row.getByRole('alert')).toBeVisible(LAUNCH)
    await expect(row).toContainText('Not installed')
    await expect(row.getByRole('alert')).toContainText('Failed to connect')
  })
})

test.describe('Claude, not installed and signed out', () => {
  test.use({ worldOptions: { noClaude: true, signedIn: false }, seed: before((world) => standInCurl(world)) })

  test('a working install says nothing failed and leads to Sign in with Claude', async ({ page, world }) => {
    await openSettings(page)
    const row = claudeRow(page)
    await button(row, 'Install').click()
    await button(dialog(page, 'Install the Claude command line?'), 'Install the Claude command line').click()
    await expect(row).toContainText('Not signed in.', LAUNCH)
    await expect(button(row, 'Sign in with Claude')).toBeVisible()
    expect(existsSync(join(world.scratch, 'userhome', '.local', 'bin', 'claude'))).toBe(true)
    await expect(row.getByRole('alert')).toHaveCount(0)
  })
})

test.describe('Claude, doctor failing', () => {
  test('the row cannot read the sign-in and offers Check again, which recovers once doctor answers', async ({ page, world }) => {
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible(LAUNCH)
    world.faults({ tools: { doctor: { error: 'doctor could not run: the profile is locked' } } })
    await goToSettings(page)
    const row = claudeRow(page)
    await expect(row).toContainText('The other door could not read the Claude sign-in.')
    world.clearFaults()
    await button(row, 'Check again').click()
    await expect(row).toContainText(`Signed in as ${world.persona.email} (Max)`)
  })
})

// --------------------------------------------------------------------------- Google Drive

test.describe('Google Drive, not connected', () => {
  test('Connect waits for the browser, then syncs at once: this computer’s data goes to an empty Drive', async ({ page, world }) => {
    await openSettings(page)
    const row = driveRow(page)
    await expect(row).toContainText('Keeps this computer and another one in step.')
    world.faults({ tools: { connect_drive: { delay_s: 2, once: true } } })
    await button(row, 'Connect').click()
    await expect(row.getByText('Waiting for you to allow access in the browser (up to five minutes), then syncing…')).toBeVisible()
    await expect(row.getByText("Sent this computer's data to Drive.")).toBeVisible()
    await expect(row).toContainText(`${world.persona.email} · last synced Oct 26, `)
    await expect(button(row, 'Disconnect')).toBeVisible()
    const state = readDriveState(world)!
    expect(state.account).toBe(world.persona.email)
    expect(state.refresh_token).toBeTruthy()
    expect(tarList(driveArchive(world))).toEqual(expect.arrayContaining(['manifest.json', 'profile/config.json', 'jobs/applications.json']))
    expect(world.toolCalls('sync_data').map((c) => c.args)).toEqual([NO_CHOICE])
  })
})

test.describe('Google Drive, connected', () => {
  test.use({ worldOptions: { drive: { connected: true } } })

  test('opening the app syncs once: this computer’s data goes to an empty Drive, and the row says when', { tag: '@core' }, async ({ page, world }) => {
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible(LAUNCH)
    await expect.poll(() => world.toolCalls('sync_data').map((c) => c.args)).toEqual([NO_CHOICE])
    await expect.poll(() => existsSync(driveArchive(world))).toBe(true)
    expect(tarList(driveArchive(world))).toEqual(expect.arrayContaining(['manifest.json', 'profile/config.json', 'jobs/applications.json']))
    const state = readDriveState(world)!
    expect(state.synced_version).toBe(md5(driveArchive(world)))
    await goToSettings(page)
    const row = driveRow(page)
    await expect(row).toContainText(/last synced Oct 26, \d\d:\d\d/)
    await expect(row.getByRole('button')).toHaveText(['Disconnect'])
    // Settings syncs nothing of its own
    expect(world.toolCalls('sync_data')).toHaveLength(1)
  })

  test('Disconnect asks first: Cancel keeps it; Disconnect sends the last changes, then forgets Drive and leaves the copy there', async ({ page, world }) => {
    await openSettings(page)
    await expect.poll(() => world.toolCalls('sync_data')).toHaveLength(1)
    const row = driveRow(page)
    await button(row, 'Disconnect').click()
    const ask = dialog(page, 'Disconnect Google Drive?')
    await expect(ask).toContainText('The last changes go to Drive first, then this computer stops syncing. The copy on Drive stays, and you can connect again later.')
    await button(ask, 'Cancel').click()
    await expect(ask).toHaveCount(0)
    expect(world.toolCalls('disconnect_drive')).toEqual([])
    expect(readDriveState(world)).not.toBeNull()

    writeFileSync(join(world.home, 'jobs', 'notes-from-this-computer.txt'), 'Call Sundline back on Thursday.\n')
    await button(row, 'Disconnect').click()
    await button(ask, 'Disconnect').click()
    await expect(row.getByText('Disconnected. The copy on Drive stays.')).toBeVisible()
    await expect(row).toContainText('Keeps this computer and another one in step.')
    await expect(button(row, 'Connect')).toBeVisible()
    expect(world.toolCalls('sync_data').map((c) => c.args)).toEqual([NO_CHOICE, NO_CHOICE])
    expect(tarList(driveArchive(world))).toContain('jobs/notes-from-this-computer.txt')
    expect(existsSync(driveState(world))).toBe(false)
  })
})

test.describe('Google Drive, connected, Drive unreachable', () => {
  test.use({
    worldOptions: { drive: { connected: true } },
    seed: before((world) => world.faults({ drive: { upload: 'Google Drive upload failed (HTTP 403)' } })),
  })

  test('a sync on opening that fails: the sidebar says so, and the row says why', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible(LAUNCH)
    await button(needsYou(page), 'Google Drive sync failed').click()
    const row = driveRow(page)
    await expect(row.getByText('The last sync failed: Google Drive upload failed (HTTP 403)')).toBeVisible()
    await expect(row.getByRole('alert')).toHaveCount(0)
  })
})

/** The home exported to Drive as another computer would have left it, then a change on this one. */
function driveHasAnOlderCopy(world: Parameters<typeof exportHome>[0]): void {
  mkdirSync(join(world.dir, 'drive'), { recursive: true })
  exportHome(world, driveArchive(world))
  writeFileSync(join(world.home, 'jobs', 'notes-from-this-computer.txt'), 'Call Sundline back on Thursday.\n')
}

test.describe('Google Drive, Drive changed since this computer synced', () => {
  test.use({
    worldOptions: { drive: { connected: true } },
    seed: before((world) => {
      driveHasAnOlderCopy(world)
      // this computer last synced another version, and has not changed since
      patchDriveState(world, { synced_version: 'an-older-version', fingerprint: fingerprint(world) })
    }),
  })

  test('opening the app brings Drive’s data here, keeping this computer’s in backups/, and reads it again', async ({ page, world }) => {
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible(LAUNCH)
    await expect.poll(() => world.exists('jobs/notes-from-this-computer.txt')).toBe(false)
    const backups = readdirSync(join(world.home, 'backups'))
    expect(backups).toHaveLength(1)
    expect(existsSync(join(world.home, 'backups', backups[0]!, 'jobs', 'notes-from-this-computer.txt'))).toBe(true)
    expect(readDriveState(world)!.synced_version).toBe(md5(driveArchive(world)))
    // a pull is new data: the screens read it again
    await expect.poll(() => world.toolCalls('show_profile').length).toBeGreaterThan(1)
  })
})

test.describe('Google Drive, both sides changed', () => {
  test.use({ worldOptions: { drive: { connected: true } }, seed: before(driveHasAnOlderCopy) })

  test('opening the app replaces nothing: a line opens Settings, where the row asks which to keep; Not now puts it away', async ({ page, world }) => {
    const before = md5(driveArchive(world))
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible(LAUNCH)
    await button(needsYou(page), 'Google Drive needs a choice').click()
    const row = driveRow(page)
    await expect(row).toContainText('This computer and Drive both changed since they last synced. Nothing was replaced.')
    await expect(row).toContainText("Keep this computer: its data replaces the copy on Drive.")
    await expect(row).toContainText("Keep Drive: Drive's data replaces this computer's, which is kept as a backup.")
    await expect(button(row, 'Disconnect')).toHaveCount(0)
    await expect(row.getByRole('alert')).toHaveCount(0)
    expect(md5(driveArchive(world))).toBe(before)
    expect(world.exists('jobs/notes-from-this-computer.txt')).toBe(true)
    expect(world.exists('backups')).toBe(false)

    await button(row, 'Not now').click()
    await expect(button(row, 'Disconnect')).toBeVisible()
    await expect(row.getByText('This computer and Drive both changed', { exact: false })).toHaveCount(0)
    await expect(needsYou(page).getByRole('button', { name: 'Google Drive needs a choice' })).toHaveCount(0)
  })

  test('Keep this computer sends its data to Drive, replacing the copy there', async ({ page, world }) => {
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible(LAUNCH)
    await button(needsYou(page), 'Google Drive needs a choice').click()
    const row = driveRow(page)
    await button(row, 'Keep this computer').click()
    await expect(row.getByText("Sent this computer's data to Drive.")).toBeVisible()
    expect(tarList(driveArchive(world))).toContain('jobs/notes-from-this-computer.txt')
    expect(world.exists('jobs/notes-from-this-computer.txt')).toBe(true)
    expect(world.toolCalls('sync_data').map((c) => c.args)).toEqual([NO_CHOICE, { keep_local: true, keep_drive: false }])
  })

  test('Keep Drive brings Drive’s data here; this computer’s is kept in backups/', async ({ page, world }) => {
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible(LAUNCH)
    await button(needsYou(page), 'Google Drive needs a choice').click()
    const row = driveRow(page)
    await button(row, 'Keep Drive').click()
    await expect(row.getByText("Brought Drive's data to this computer.")).toBeVisible()
    expect(world.exists('jobs/notes-from-this-computer.txt')).toBe(false)
    const backups = readdirSync(join(world.home, 'backups'))
    expect(existsSync(join(world.home, 'backups', backups[0]!, 'jobs', 'notes-from-this-computer.txt'))).toBe(true)
    expect(tarList(driveArchive(world))).not.toContain('jobs/notes-from-this-computer.txt')
  })
})

test.describe('Google Drive, the last background sync failed', () => {
  test.use({
    worldOptions: { drive: { connected: true } },
    seed: before((world) => {
      patchDriveState(world, { last_synced: '2026-10-25T16:40:00+00:00', last_error: 'Google Drive is unreachable (ConnectionError)' })
      // still unreachable when the app opens and syncs
      world.faults({ drive: { upload: 'Google Drive is unreachable (ConnectionError)' } })
    }),
  })

  test('the sidebar says Google Drive sync failed and opens Settings, where the row says why', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible(LAUNCH)
    await button(needsYou(page), 'Google Drive sync failed').click()
    await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible()
    const row = driveRow(page)
    await expect(row.getByText('The last sync failed: Google Drive is unreachable (ConnectionError)')).toBeVisible()
    await expect(row).toContainText(/last synced Oct 25, \d\d:\d\d/)
  })
})

// --------------------------------------------------------------------------- the phone

// The Your phone row is not rendered in Settings for now (#650); its journeys wait for it.
test.describe.skip('Your phone', () => {

  test('Continue, the QR code at once, the phone scans it, Done: the row says it is paired', async ({ page, world }) => {
    await openSettings(page)
    const row = phoneRow(page)
    await button(row, 'Set up your phone').click()
    const setup = dialog(page, 'Set up your phone')
    await button(setup, 'Continue').click()
    await expect(setup).toContainText('Serving at https://quiet-river.trycloudflare.example. This address changes when this computer restarts.')
    await expect(setup.getByRole('img', { name: 'QR code that pairs your phone' })).toBeVisible()
    await expect(setup.getByRole('textbox')).toHaveCount(0)
    await expect(setup).toContainText("Point your phone's camera at the code and open the link it shows. It works once, for five minutes.")
    await expect(setup.getByText('Waiting for your phone…')).toBeVisible()
    expect(world.toolCalls('phone_start').map((c) => c.args)).toEqual([{ connection: 'cloudflare' }])
    expect(world.toolCalls('pair_phone').map((c) => c.args)).toEqual([{ device: 'My phone' }])

    phoneScans(world)
    await expect(setup.getByRole('heading', { name: 'Add The other door to your home screen' })).toBeVisible()
    await expect(setup).toContainText('Your phone is paired.')
    await expect(setup).toContainText('Android: in Chrome, open the menu (⋮) and tap Install app.')
    await expect(setup).toContainText('iPhone: in Safari, tap Share, then Add to Home Screen.')
    await expect(setup).toContainText('When this computer restarts, set this up again and scan the new code.')
    await button(setup, 'Done').click()
    await expect(setup).toHaveCount(0)
    await expect(row).toContainText('Connected until this computer restarts')
    await expect(row).not.toContainText('My phone')
    await expect(row).not.toContainText('trycloudflare')
    await expect(button(row, 'Disconnect')).toBeVisible()
  })

  test('closed before the scan: Pair your phone brings the code back; Disconnect asks, then unpairs and stops', async ({ page, world }) => {
    await openSettings(page)
    const row = phoneRow(page)
    await button(row, 'Set up your phone').click()
    const setup = dialog(page, 'Set up your phone')
    await button(setup, 'Continue').click()
    await expect(setup.getByRole('img', { name: 'QR code that pairs your phone' })).toBeVisible()
    await button(setup, 'Close').click()
    await expect(row).toContainText('Not paired yet.')

    await button(row, 'Pair your phone').click()
    await expect(setup.getByRole('img', { name: 'QR code that pairs your phone' })).toBeVisible()
    await expect(setup.getByText('Serving at', { exact: false })).toHaveCount(0)
    phoneScans(world)
    await button(setup, 'Done').click()
    await expect(row).toContainText('Connected until this computer restarts')

    const ask = dialog(page, 'Disconnect your phone?')
    await button(row, 'Disconnect').click()
    await button(ask, 'Cancel').click()
    await expect(ask).toHaveCount(0)
    world.faults({ tools: { unpair_phone: { error: "no paired phone is called 'My phone'", once: true } } })
    await button(row, 'Disconnect').click()
    await button(ask, 'Disconnect').click()
    await expect(row.getByRole('alert')).toHaveText("no paired phone is called 'My phone'")
    expect(world.toolCalls('phone_stop')).toHaveLength(0)
    await button(row, 'Disconnect').click()
    await button(ask, 'Disconnect').click()
    await expect(button(row, 'Set up your phone')).toBeVisible()
    await expect(row.getByRole('alert')).toHaveCount(0)
    expect(world.toolCalls('unpair_phone').map((c) => c.args)).toEqual([{ device: 'My phone' }, { device: 'My phone' }])
    expect(world.toolCalls('phone_stop')).toHaveLength(1)
  })

  test('phone_status failing still leaves a way to try again in the row', async ({ page, world }) => {
    await expect(page.getByRole('heading', { name: 'Matches', level: 1 })).toBeVisible(LAUNCH)
    world.faults({ tools: { phone_status: { error: 'the phone server state is unreadable', once: true } } })
    await goToSettings(page)
    const row = phoneRow(page)
    await expect(row.getByRole('alert')).toBeVisible()
    await expect(row.getByRole('button')).not.toHaveCount(0, { timeout: 3000 })
  })
})
