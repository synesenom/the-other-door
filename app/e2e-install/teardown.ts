// The install test's (#639) global teardown: uninstall what setup.ts installed and remove its throwaway folder
// (each test's world is removed by the journeys' own teardown). DOOR_INSTALL_KEEP=1 keeps the app to look at.
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, rmSync } from 'node:fs'
import { endRun } from '../journeys/teardown'
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
  for (const argv of plan.uninstall) {
    try {
      execFileSync(argv[0]!, argv.slice(1), { stdio: 'inherit' })
    } catch (e) {
      console.error(`could not uninstall: ${argv.join(' ')}: ${e instanceof Error ? e.message : e}`)
    }
  }
  if (scratch) rmSync(scratch, { recursive: true, force: true })
}
