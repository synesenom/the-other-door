// Electron (43) has no postinstall: its binary is downloaded and unpacked on the first require('electron'), with no
// lock between processes. Two workers launching their first app at once both found it missing, both unpacked it, and
// one spawned the binary while the other was still writing it: `spawn ETXTBSY` on Linux, the first test of a CI shard
// and its retry (#126). The journeys' global setup fetches it here, once, before any worker starts.
import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

/** Electron's download may stall; past this the run fails instead of hanging. */
export const DOWNLOAD_TIMEOUT_MS = 5 * 60_000

const ELECTRON = dirname(require.resolve('electron'))

export interface ElectronIo {
  /** The binary's path from Electron's path.txt, or null before any download. */
  binary: () => string | null
  exists: (path: string) => boolean
  install: (timeoutMs: number) => void
}

type Runner = (script: string, timeoutMs: number) => { status: number | null; error?: Error & { code?: string } }

const runNode: Runner = (script, timeoutMs) => spawnSync(process.execPath, [script], { stdio: 'inherit', timeout: timeoutMs })

/** Electron's own install.js (what require('electron') runs), bounded: a stalled download fails with a reason. */
export function installElectron(timeoutMs: number, run: Runner = runNode): void {
  const result = run(join(ELECTRON, 'install.js'), timeoutMs)
  if (result.error?.code === 'ETIMEDOUT') throw new Error(`Electron's binary did not download in ${timeoutMs / 60_000} minutes`)
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`Electron's binary download failed (exit ${result.status})`)
}

const realIo: ElectronIo = {
  binary: () => {
    const pathFile = join(ELECTRON, 'path.txt')
    return existsSync(pathFile) ? join(ELECTRON, 'dist', readFileSync(pathFile, 'utf8')) : null
  },
  exists: existsSync,
  install: (timeoutMs) => installElectron(timeoutMs),
}

/** The Electron binary's path, downloaded now if it is not in place; throws when it is still missing after. */
export function ensureElectron(io: ElectronIo = realIo, timeoutMs = DOWNLOAD_TIMEOUT_MS): string {
  let binary = io.binary()
  if (binary === null || !io.exists(binary)) {
    io.install(timeoutMs)
    binary = io.binary()
  }
  if (binary === null || !io.exists(binary)) throw new Error(`Electron's binary is missing after its download: ${binary ?? 'no path.txt'}`)
  return binary
}
