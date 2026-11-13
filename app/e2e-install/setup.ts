// The install test's (#639) global setup: install the installer a user downloads, the user's way, into a
// throwaway folder, and report its signature. Its executable goes to the tests as DOOR_INSTALLED_APP
// (journeys/fixtures.ts launches it); teardown.ts removes it again.
//
//   DOOR_INSTALLER=<file>        the installer to test (default: this system's newest in dist/)
//   DOOR_INSTALLER_KIND=deb      on Linux, the .deb instead of the AppImage
//   DOOR_INSTALLED_APP=<exe>     an app already installed: no install, no uninstall
import { execFileSync, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { startRun } from '../journeys/teardown'
import { installPlan, pickInstaller, signingCommands, type Kind } from './installer'

const APP = resolve(__dirname, '..')
export const STATE = join(APP, 'install-report', 'state.json')
export const SIGNING = join(APP, 'install-report', 'signing.txt')

function installer(): string {
  if (process.env.DOOR_INSTALLER) return resolve(process.env.DOOR_INSTALLER)
  const dist = join(APP, 'dist')
  const files = existsSync(dist) ? readdirSync(dist) : []
  const found = pickInstaller(files, process.platform, process.arch, process.env.DOOR_INSTALLER_KIND as Kind | undefined)
  if (!found) throw new Error(`no installer for ${process.platform}-${process.arch} in dist/: run \`npm run package\`, or set DOOR_INSTALLER`)
  return join(dist, found)
}

/** What a user meets when opening it: the signature, written to install-report/signing.txt and printed. */
function reportSigning(executable: string): void {
  const out: string[] = []
  for (const argv of signingCommands(process.platform, executable)) {
    const r = spawnSync(argv[0]!, argv.slice(1), { encoding: 'utf8' })
    out.push(`$ ${argv.join(' ')}  (exit ${r.status})`, (r.stdout + r.stderr).trim(), '')
  }
  if (!out.length) out.push('Linux builds are not signed.')
  writeFileSync(SIGNING, out.join('\n') + '\n')
  console.log(`\nSignature of the installed app (not judged):\n${out.join('\n')}`)
}

export default function setup(): void {
  startRun()
  mkdirSync(join(APP, 'install-report'), { recursive: true })
  if (process.env.DOOR_INSTALLED_APP) {
    writeFileSync(STATE, JSON.stringify({ plan: null }))
    reportSigning(process.env.DOOR_INSTALLED_APP)
    return
  }
  const file = installer()
  const root = mkdtempSync(join(tmpdir(), 'door-install-'))
  const plan = installPlan(file, process.platform, root)
  console.log(`\nInstalling ${file}\n  into ${plan.root ?? 'the system (apt)'}`)
  writeFileSync(STATE, JSON.stringify({ plan, scratch: root }))
  for (const argv of plan.install) execFileSync(argv[0]!, argv.slice(1), { stdio: 'inherit' })
  if (!existsSync(plan.executable)) throw new Error(`installed, but there is no ${plan.executable}`)
  process.env.DOOR_INSTALLED_APP = plan.executable
  reportSigning(plan.executable)
}
