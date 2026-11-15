// The install test's (#639) global teardown: uninstall what setup.ts installed and remove its throwaway folder; a failed uninstall fails the run
// (each test's world is removed by the journeys' own teardown). DOOR_INSTALL_KEEP=1 keeps the app to look at.
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, rmSync } from 'node:fs'
import { endRun } from '../journeys/teardown'
import { uninstallFailures } from './installer'
import type { Plan } from './installer'
import { STATE } from './setup'

export default function teardown(): void {
  endRun()
  if (!existsSync(STATE)) return
  const { plan, scratch } = JSON.parse(readFileSync(STATE, 'utf8')) as { plan: Plan | null; scratch?: string }
  if (!plan) return
  if (process.env.DOOR_INSTALL_KEEP === '1') {
    console.log(`\nKept the installed app: ${plan.executable}`)
    return
  }
  const failures = uninstallFailures(plan, process.platform, {
    run: (argv) => void execFileSync(argv[0]!, argv.slice(1), { stdio: 'inherit' }),
    exists: existsSync,
    wait: (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms),
  })
  if (scratch) rmSync(scratch, { recursive: true, force: true })
  if (failures.length) throw new Error(`The uninstall failed:\n${failures.join('\n')}`)
}
