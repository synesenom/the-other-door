import { describe, expect, it } from 'vitest'
import { bundledPython, documentedDataFolder, errorLines, installPlan, layEnv, pickInstaller, resourcesOf, signingCommands } from './installer'

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
    const plan = installPlan('C:\\d\\the-other-door-0.1.1-windows-x64.exe', 'win32', 'C:\\t')
    expect(plan.install).toEqual([['C:\\d\\the-other-door-0.1.1-windows-x64.exe', '/S', '/D=C:\\t\\app']])
    expect(plan.executable).toBe('C:\\t\\app\\the-other-door.exe')
    expect(plan.uninstall).toEqual([['C:\\t\\app\\Uninstall The other door.exe', '/S']])
  })

  it('Linux: the AppImage copied and made executable; the .deb through apt, into /opt, removed by its package name', () => {
    const image = installPlan('/d/the-other-door-0.1.1-linux-x64.AppImage', 'linux', '/t')
    expect(image.install).toEqual([
      ['cp', '/d/the-other-door-0.1.1-linux-x64.AppImage', '/t/the-other-door-0.1.1-linux-x64.AppImage'],
      ['chmod', '+x', '/t/the-other-door-0.1.1-linux-x64.AppImage'],
    ])
    expect(image.executable).toBe('/t/the-other-door-0.1.1-linux-x64.AppImage')
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
    expect(resourcesOf('/t/the-other-door-0.1.1-linux-x64.AppImage', 'linux')).toBeNull()
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
