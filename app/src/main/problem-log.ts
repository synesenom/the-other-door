// The app's lines in the problem log (#593): `<data folder>/logs/door.log`, the file door's server writes
// (src/door/core/problem_log.py), in its format: what the window was refused, and the server's crashes
// with the end of its stderr. `Save logs…` packs it. It writes one file and spawns nothing.
import { appendFileSync, existsSync, mkdirSync, renameSync, statSync } from 'node:fs'
import { join } from 'node:path'

/** As the server's log: rotated at about 1 MB, keeping door.log.1 and door.log.2. */
export const MAX_BYTES = 1_000_000
const BACKUPS = 2
const MAX_MESSAGE = 2000

export interface ProblemLog {
  write(where: string, message: string): void
}

function rotate(file: string): void {
  for (let n = BACKUPS - 1; n >= 1; n--) {
    if (existsSync(`${file}.${n}`)) renameSync(`${file}.${n}`, `${file}.${n + 1}`)
  }
  renameSync(file, `${file}.1`)
}

export function createProblemLog(home: string, deps: { now?: () => Date } = {}): ProblemLog {
  const now = deps.now ?? (() => new Date())
  const file = join(home, 'logs', 'door.log')
  return {
    write(where, message) {
      try {
        if (!existsSync(home)) return // no data folder: nothing to write into, and nothing is made
        mkdirSync(join(home, 'logs'), { recursive: true })
        if (existsSync(file) && statSync(file).size >= MAX_BYTES) rotate(file)
        const text = message.split(/\s+/).filter(Boolean).join(' ').slice(0, MAX_MESSAGE)
        const at = now().toISOString().replace(/\.\d+Z$/, 'Z')
        appendFileSync(file, `${at} ERROR app ${where}: ${text}\n`, 'utf8')
      } catch {
        // the log is a courtesy: never the reason something else fails
      }
    },
  }
}
