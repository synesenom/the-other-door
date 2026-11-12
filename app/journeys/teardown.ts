// Each test builds its world in a temp folder (test/world/build.ts). Removing it as the test ends races
// the server, which may still be writing its lock and log as it exits; so the run removes them at its end
// instead: every world made since the run began, except those of failed tests (kept to look at).
import { appendFileSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const STATE = resolve(__dirname, '..', 'journeys-report')
const STARTED = join(STATE, '.run-started')
const KEPT = join(STATE, 'kept-worlds.txt')

/** Called by the world fixture for a failed test. */
export function keepWorld(scratch: string): void {
  mkdirSync(STATE, { recursive: true })
  appendFileSync(KEPT, `${scratch}\n`)
}

export function startRun(): void {
  mkdirSync(STATE, { recursive: true })
  writeFileSync(STARTED, String(Date.now()))
  writeFileSync(KEPT, '')
}

export function endRun(): void {
  let started = 0
  let kept: string[] = []
  try {
    started = Number(readFileSync(STARTED, 'utf8'))
    kept = readFileSync(KEPT, 'utf8').split('\n').filter(Boolean)
  } catch {
    return
  }
  for (const name of readdirSync(tmpdir())) {
    if (!name.startsWith('door-world-')) continue
    const dir = join(tmpdir(), name)
    try {
      if (statSync(dir).birthtimeMs >= started && !kept.includes(dir)) rmSync(dir, { recursive: true, force: true })
    } catch {
      // gone already, or not ours to remove
    }
  }
}
