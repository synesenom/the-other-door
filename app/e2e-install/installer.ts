// The install test's (#639) pure part: which installer to take, how a user installs it on each system, where
// the installed app's executable and resources end up, how it is removed, and where its data folder is.
// No process is started here; install.e2e.ts runs the plan.
import { posix, win32 } from 'node:path'

export type Kind = 'dmg' | 'exe' | 'appimage' | 'deb'

/** The installer kinds a system takes, the user's first choice first. */
export function kindsFor(platform: string): Kind[] {
  if (platform === 'darwin') return ['dmg']
  if (platform === 'win32') return ['exe']
  return ['appimage', 'deb']
}

export function kindOf(file: string): Kind | null {
  const lower = file.toLowerCase()
  if (lower.endsWith('.dmg')) return 'dmg'
  if (lower.endsWith('.exe')) return 'exe'
  if (lower.endsWith('.appimage')) return 'appimage'
  if (lower.endsWith('.deb')) return 'deb'
  return null
}

const versionOf = (file: string): number[] => (/-(\d+)\.(\d+)\.(\d+)-/.exec(file) ?? []).slice(1).map(Number)

function newer(a: number[], b: number[]): number {
  for (let i = 0; i < 3; i++) if ((a[i] ?? 0) !== (b[i] ?? 0)) return (b[i] ?? 0) - (a[i] ?? 0)
  return 0
}

/**
 * The installer to test among the files of `dist/` (the release's names, `the-other-door-<v>-<os>-<arch>.<ext>`):
 * this system's, this architecture's (Windows takes the x64 build anywhere: on ARM it runs emulated), the
 * newest version. `kind` picks between a system's kinds (Linux: AppImage, else `.deb`).
 */
export function pickInstaller(files: string[], platform: string, arch: string, kind?: Kind): string | null {
  const kinds = kind ? [kind] : kindsFor(platform)
  const os = platform === 'darwin' ? 'mac' : platform === 'win32' ? 'windows' : 'linux'
  const builds = platform === 'win32' ? ['x64'] : platform === 'linux' && arch === 'x64' ? ['x64', 'amd64'] : [arch]
  for (const k of kinds) {
    const found = files
      .filter((f) => kindOf(f) === k && f.includes(`-${os}-`) && builds.some((b) => f.includes(`-${b}.`) || f.includes(`_${b}.`)))
      .sort((a, b) => newer(versionOf(a), versionOf(b)))
    if (found[0]) return found[0]
  }
  return null
}

export interface Plan {
  kind: Kind
  /** The commands that install it, in order. */
  install: string[][]
  /** The installed app's executable (for an AppImage, the AppImage itself). */
  executable: string
  /** The commands that remove it again (after which `root` is deleted). */
  uninstall: string[][]
  /** The throwaway folder it goes into; `null` for the `.deb`, which apt installs system-wide. */
  root: string | null
}

const APP_NAME = 'The other door'
const EXE_NAME = 'the-other-door'
/** The `.deb`'s package name: package.json's `name`. */
export const DEB_PACKAGE = 'door-app'

/** How a user installs `installer`, into the throwaway folder `root` where the system allows it. */
export function installPlan(installer: string, platform: string, root: string): Plan {
  const kind = kindOf(installer)
  if (!kind) throw new Error(`not an installer: ${installer}`)
  const p = platform === 'win32' ? win32 : posix
  switch (kind) {
    case 'dmg': {
      // open the .dmg and drag the app into a folder: here a throwaway one instead of /Applications
      const mount = p.join(root, 'volume')
      const app = p.join(root, `${APP_NAME}.app`)
      return {
        kind,
        install: [
          ['hdiutil', 'attach', '-nobrowse', '-readonly', '-noautoopen', '-mountpoint', mount, installer],
          ['ditto', p.join(mount, `${APP_NAME}.app`), app],
          ['hdiutil', 'detach', mount],
        ],
        executable: p.join(app, 'Contents', 'MacOS', APP_NAME),
        uninstall: [],
        root,
      }
    }
    case 'exe': {
      // the NSIS installer, silently, for this user only; /D= must come last and unquoted
      const dir = p.join(root, 'app')
      return {
        kind,
        install: [[installer, '/S', `/D=${dir}`]],
        executable: p.join(dir, `${EXE_NAME}.exe`),
        uninstall: [[p.join(dir, `Uninstall ${APP_NAME}.exe`), '/S']],
        root,
      }
    }
    case 'appimage': {
      const target = p.join(root, p.basename(installer))
      return { kind, install: [['cp', installer, target], ['chmod', '+x', target]], executable: target, uninstall: [], root }
    }
    case 'deb':
      // apt wants a path, not a bare name; it installs into /opt for every user (sudo asks once)
      return {
        kind,
        install: [['sudo', 'apt-get', 'install', '-y', posix.isAbsolute(installer) ? installer : `./${installer}`]],
        executable: posix.join('/opt', APP_NAME, EXE_NAME),
        uninstall: [['sudo', 'apt-get', 'remove', '-y', DEB_PACKAGE]],
        root: null,
      }
  }
}

/** The installed app's resources (the bundle: python/, door/, bin/) next to its executable; an AppImage's only at run time. */
export function resourcesOf(executable: string, platform: string): string | null {
  if (kindOf(executable) === 'appimage') return null
  const p = platform === 'win32' ? win32 : posix
  return platform === 'darwin' ? p.resolve(p.dirname(executable), '..', 'Resources') : p.join(p.dirname(executable), 'resources')
}

/** The bundled Python inside `resources`, as the packaged app starts it (src/main/door-server.ts). */
export function bundledPython(resources: string, platform: string): string {
  return platform === 'win32' ? win32.join(resources, 'python', 'python.exe') : posix.join(resources, 'python', 'bin', 'python3')
}

/** Where the data folder is when nothing overrides it, as docs/manual-app.md says ("Your data"). */
export function documentedDataFolder(platform: string, home: string, appData?: string): string {
  if (platform === 'darwin') return posix.join(home, 'Library', 'Application Support', APP_NAME)
  if (platform === 'win32') return win32.join(appData ?? win32.join(home, 'AppData', 'Roaming'), APP_NAME)
  return posix.join(home, '.config', APP_NAME)
}

/**
 * `base` with `over` laid on top, a key of `over` replacing `base`'s whatever its case (Windows' `Path` and
 * the world's `PATH` are one variable: both in one environment would leave the child to pick).
 */
export function layEnv(base: Record<string, string | undefined>, over: Record<string, string>): Record<string, string> {
  const replaced = new Set(Object.keys(over).map((k) => k.toUpperCase()))
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(base)) if (v !== undefined && !replaced.has(k.toUpperCase())) out[k] = v
  return { ...out, ...over }
}

/** The ERROR lines of a problem log (`<UTC time> <LEVEL> <where>: <message>`, core/problem_log.py and main/problem-log.ts). */
export function errorLines(log: string): string[] {
  return log.split(/\r?\n/).filter((l) => /^\S+ ERROR /.test(l))
}

/** The commands that show the signature a user meets (reported, not judged while the builds are unsigned). */
export function signingCommands(platform: string, executable: string): string[][] {
  if (platform === 'darwin') {
    const app = posix.resolve(posix.dirname(executable), '..', '..')
    return [
      ['codesign', '--display', '--verbose=2', app],
      ['spctl', '--assess', '--type', 'execute', '--verbose=2', app],
    ]
  }
  if (platform === 'win32') {
    const quoted = executable.replace(/'/g, "''")
    return [['powershell', '-NoProfile', '-Command', `Get-AuthenticodeSignature '${quoted}' | Format-List Status,StatusMessage,SignerCertificate`]]
  }
  return []
}
