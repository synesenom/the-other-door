import { describe, expect, it } from 'vitest'
import { bundledPython, documentedDataFolder, errorLines, installPlan, layEnv, pickInstaller, resourcesOf, removeInstall, signingCommands, uninstallFailures } from './installer'
import type { Plan } from './installer'

const DIST = [
  'the-other-door-0.1.0-mac-arm64.dmg',
  'the-other-door-0.1.0-mac-arm64.zip',
  'the-other-door-0.1.1-mac-arm64.dmg',
  'the-other-door-0.1.1-mac-arm64.dmg.blockmap',
  'the-other-door-0.1.1-mac-x64.dmg',
  'The-other-door-0.1.1-Windows.exe',
  'The-other-door-0.1.1-Windows.exe.blockmap',
  'The-other-door-0.1.1-Linux.AppImage',
  'the-other-door-0.1.1-linux-amd64.deb',
  'latest-mac.yml',
  'latest.yml',
  'latest-linux.yml',
]

describe('pickInstaller', () => {
  it('takes this system’s and architecture’s installer, the newest version', () => {
    expect(pickInstaller(DIST, 'darwin', 'arm64')).toBe('the-other-door-0.1.1-mac-arm64.dmg')
    expect(pickInstaller(DIST, 'darwin', 'x64')).toBe('the-other-door-0.1.1-mac-x64.dmg')
  })

  it('takes the x64 build on Windows on ARM, which runs it emulated', () => {
    expect(pickInstaller(DIST, 'win32', 'arm64')).toBe('The-other-door-0.1.1-Windows.exe')
  })

  it('takes the AppImage on Linux unless the .deb is asked for', () => {
    expect(pickInstaller(DIST, 'linux', 'x64')).toBe('The-other-door-0.1.1-Linux.AppImage')
    expect(pickInstaller(DIST, 'linux', 'x64', 'deb')).toBe('the-other-door-0.1.1-linux-amd64.deb')
  })

  it('finds nothing for a system the folder has no build of', () => {
    expect(pickInstaller(DIST, 'linux', 'arm64')).toBeNull()
    expect(pickInstaller(['latest-mac.yml'], 'darwin', 'arm64')).toBeNull()
  })
})

describe('installPlan', () => {
  it('macOS: mounts the .dmg, copies the app into the throwaway folder, unmounts', () => {
    const plan = installPlan('/d/the-other-door-0.1.1-mac-arm64.dmg', 'darwin', '/t')
    expect(plan.install).toEqual([
      ['hdiutil', 'attach', '-nobrowse', '-readonly', '-noautoopen', '-mountpoint', '/t/volume', '/d/the-other-door-0.1.1-mac-arm64.dmg'],
      ['ditto', '/t/volume/The other door.app', '/t/The other door.app'],
      ['hdiutil', 'detach', '/t/volume'],
    ])
    expect(plan.executable).toBe('/t/The other door.app/Contents/MacOS/The other door')
    expect(plan.root).toBe('/t')
  })

  it('Windows: the NSIS installer silently into the throwaway folder, and its uninstaller', () => {
    const plan = installPlan('C:\\d\\The-other-door-0.1.1-Windows.exe', 'win32', 'C:\\t')
    expect(plan.install).toEqual([['C:\\d\\The-other-door-0.1.1-Windows.exe', '/S', '/D=C:\\t\\app']])
    expect(plan.executable).toBe('C:\\t\\app\\the-other-door.exe')
    expect(plan.uninstall).toEqual([['C:\\t\\app\\Uninstall The other door.exe', '/S']])
  })

  it('Linux: the AppImage copied and made executable; the .deb through apt, into /opt, removed by its package name', () => {
    const image = installPlan('/d/The-other-door-0.1.1-Linux.AppImage', 'linux', '/t')
    expect(image.install).toEqual([
      ['cp', '/d/The-other-door-0.1.1-Linux.AppImage', '/t/The-other-door-0.1.1-Linux.AppImage'],
      ['chmod', '+x', '/t/The-other-door-0.1.1-Linux.AppImage'],
    ])
    expect(image.executable).toBe('/t/The-other-door-0.1.1-Linux.AppImage')
    const deb = installPlan('dist/the-other-door-0.1.1-linux-amd64.deb', 'linux', '/t')
    expect(deb.install).toEqual([['sudo', 'apt-get', 'install', '-y', './dist/the-other-door-0.1.1-linux-amd64.deb']])
    expect(deb.executable).toBe('/opt/The other door/the-other-door')
    expect(deb.uninstall).toEqual([['sudo', 'apt-get', 'remove', '-y', 'door-app']])
    expect(deb.root).toBeNull()
  })

  it('refuses what is not an installer', () => {
    expect(() => installPlan('/d/latest-mac.yml', 'darwin', '/t')).toThrow(/not an installer/)
  })
})

describe('where the installed app keeps things', () => {
  it('its resources sit beside the executable, inside the bundle on macOS; an AppImage’s are known only when it runs', () => {
    expect(resourcesOf('/t/The other door.app/Contents/MacOS/The other door', 'darwin')).toBe('/t/The other door.app/Contents/Resources')
    expect(resourcesOf('C:\\t\\app\\the-other-door.exe', 'win32')).toBe('C:\\t\\app\\resources')
    expect(resourcesOf('/opt/The other door/the-other-door', 'linux')).toBe('/opt/The other door/resources')
    expect(resourcesOf('/t/The-other-door-0.1.1-Linux.AppImage', 'linux')).toBeNull()
  })

  it('the bundled Python is the one the packaged app starts', () => {
    expect(bundledPython('/r', 'darwin')).toBe('/r/python/bin/python3')
    expect(bundledPython('C:\\r', 'win32')).toBe('C:\\r\\python\\python.exe')
  })

  it('the data folder is where the manual says', () => {
    expect(documentedDataFolder('darwin', '/Users/a')).toBe('/Users/a/Library/Application Support/The other door')
    expect(documentedDataFolder('win32', 'C:\\Users\\a', 'C:\\Users\\a\\AppData\\Roaming')).toBe('C:\\Users\\a\\AppData\\Roaming\\The other door')
    expect(documentedDataFolder('linux', '/home/a')).toBe('/home/a/.config/The other door')
  })
})

describe('layEnv', () => {
  it('replaces a variable whatever its case, so Windows’ Path and the world’s PATH are not both handed on', () => {
    expect(layEnv({ Path: 'C:\\mine', HOME: '/me', KEEP: 'x', GONE: undefined }, { PATH: '/world/bin', HOME: '/world/home' })).toEqual({
      KEEP: 'x',
      PATH: '/world/bin',
      HOME: '/world/home',
    })
  })
})

describe('errorLines', () => {
  it('keeps the ERROR lines of the server’s and the app’s, not the warnings', () => {
    const log = [
      '2026-10-26T09:00:00Z WARNING find: jobindex came back empty',
      '2026-10-26T09:00:01Z ERROR prepare: the tailor failed',
      '2026-10-26T09:00:02Z ERROR app server-exit: the server stopped',
      '',
    ].join('\n')
    expect(errorLines(log)).toEqual(['2026-10-26T09:00:01Z ERROR prepare: the tailor failed', '2026-10-26T09:00:02Z ERROR app server-exit: the server stopped'])
  })
})

describe('signingCommands', () => {
  it('macOS: codesign and Gatekeeper’s assessment of the .app; Windows: its Authenticode signature; Linux: nothing to ask', () => {
    expect(signingCommands('darwin', '/t/The other door.app/Contents/MacOS/The other door')).toEqual([
      ['codesign', '--display', '--verbose=2', '/t/The other door.app'],
      ['spctl', '--assess', '--type', 'execute', '--verbose=2', '/t/The other door.app'],
    ])
    expect(signingCommands('win32', "C:\\t\\app\\the-other-door.exe")[0]!.slice(0, 3)).toEqual(['powershell', '-NoProfile', '-Command'])
    expect(signingCommands('win32', "C:\\t\\app\\the-other-door.exe")[0]![3]).toContain("Get-AuthenticodeSignature 'C:\\t\\app\\the-other-door.exe'")
    expect(signingCommands('linux', '/t/x.AppImage')).toEqual([])
  })
})

describe('uninstallFailures', () => {
  const plan = (over: Partial<Plan>): Plan => ({ kind: 'exe', install: [], executable: 'C:\\root\\app\\x.exe', uninstall: [['un', '/S']], root: 'C:\\root', ...over })

  it('is empty when every command succeeds and the folder is gone', () => {
    const f = uninstallFailures(plan({}), 'win32', { run: () => undefined, exists: () => false, wait: () => undefined })
    expect(f).toEqual([])
  })

  it('names a command that failed', () => {
    const f = uninstallFailures(plan({}), 'linux', {
      run: () => { throw new Error('exit 1') },
      exists: () => false,
      wait: () => undefined,
    })
    expect(f).toEqual(['could not uninstall: un /S: exit 1'])
  })

  it('on Windows fails when the install folder is still there after waiting', () => {
    let waits = 0
    const f = uninstallFailures(plan({}), 'win32', { run: () => undefined, exists: () => true, wait: () => { waits++ } })
    expect(waits).toBeGreaterThan(0)
    expect(f).toEqual(['the uninstaller left C:\\root\\app behind'])
  })

  it('on Windows accepts an install folder that disappears while waiting', () => {
    let n = 0
    const f = uninstallFailures(plan({}), 'win32', { run: () => undefined, exists: () => ++n < 3, wait: () => undefined })
    expect(f).toEqual([])
  })

  it('carries on after a failed command and reports a folder left behind with it', () => {
    const ran: string[] = []
    const f = uninstallFailures(plan({ uninstall: [['a'], ['b']] }), 'win32', {
      run: (argv) => { ran.push(argv[0]!); if (argv[0] === 'a') throw new Error('exit 2') },
      exists: () => true,
      wait: () => undefined,
    })
    expect(ran).toEqual(['a', 'b'])
    expect(f).toEqual(['could not uninstall: a: exit 2', 'the uninstaller left C:\\root\\app behind'])
  })

  it('does not check the folder of a plan with no throwaway root', () => {
    const f = uninstallFailures(plan({ root: null }), 'win32', { run: () => undefined, exists: () => true, wait: () => undefined })
    expect(f).toEqual([])
  })

  it('does not check the folder off Windows', () => {
    const f = uninstallFailures(plan({ kind: 'appimage', uninstall: [] }), 'linux', { run: () => undefined, exists: () => true, wait: () => undefined })
    expect(f).toEqual([])
  })
})

describe('removeInstall', () => {
  const plan: Plan = { kind: 'deb', install: [], executable: '/opt/x/x', uninstall: [['apt-get', 'remove']], root: null }
  const io = (over: Partial<Parameters<typeof removeInstall>[3]>) => ({
    run: () => undefined, exists: () => false, wait: () => undefined, rm: () => undefined, ...over,
  })

  it('removes the scratch folder and passes when the uninstall was clean', () => {
    const removed: string[] = []
    expect(() => removeInstall(plan, '/tmp/s', 'linux', io({ rm: (p) => { removed.push(p) } }))).not.toThrow()
    expect(removed).toEqual(['/tmp/s'])
  })

  it('fails the run on a failed uninstall, after still removing the scratch folder', () => {
    const removed: string[] = []
    expect(() => removeInstall(plan, '/tmp/s', 'linux', io({ run: () => { throw new Error('exit 100') }, rm: (p) => { removed.push(p) } })))
      .toThrow(/The uninstall failed:\ncould not uninstall: apt-get remove: exit 100/)
    expect(removed).toEqual(['/tmp/s'])
  })

  it('keeps the uninstall failure in the message when removing the scratch folder fails too', () => {
    expect(() => removeInstall(plan, '/tmp/s', 'linux', io({ run: () => { throw new Error('exit 100') }, rm: () => { throw new Error('EBUSY') } })))
      .toThrow(/could not uninstall: apt-get remove: exit 100\ncould not remove \/tmp\/s: EBUSY/)
  })
})
