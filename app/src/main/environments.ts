// The app's three environments (app/README.md "Environments"): which one this start is, its data folder,
// and the server's environment there. Pure, but `prepare`, which makes the folder.
//
// - production: the installed app, or `npm run dev` from a checkout, on your data and your Drive.
// - staging (`npm run dev:staging`, `:fresh` empties it): everything real, on a throwaway folder app/.staging/;
//   Drive refused, so the throwaway data never reaches your archive.
// - sandbox (`npm run dev:sandbox`, `:fresh` builds it again, `:empty` starts with nothing): app/.sandbox/, the
//   made-up data of sandbox.ts or nothing; "Find new jobs" is simulated (demo-run.ts) and Drive refused, the
//   rest is real (claude on your plan, the style build, Prepare).
import { mkdirSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { refuseRealData, seedSandbox } from './sandbox'

export type Environment = 'production' | 'staging' | 'sandbox'

/** How the sandbox starts: kept, made again from the made-up data, or empty (the wizard opens). */
export type SandboxStart = 'keep' | 'fresh' | 'empty'

export type Start =
  | { environment: 'production' }
  | { environment: 'staging'; folder: string; fresh: boolean }
  | { environment: 'sandbox'; folder: string; start: SandboxStart }

type Env = Record<string, string | undefined>

/**
 * This start, from electron-vite's `--mode` (staging, staging-fresh, sandbox, sandbox-fresh, sandbox-empty) or, in a
 * built app, `DOOR_SANDBOX_DIR` (how the tests run the sandbox; `DOOR_SANDBOX_EMPTY=1` starts it empty). A packaged
 * app is always production.
 */
export function startFor(mode: string | undefined, env: Env, packaged: boolean, repoRoot: string): Start {
  if (packaged) return { environment: 'production' }
  if (mode === 'staging' || mode === 'staging-fresh') return { environment: 'staging', folder: join(repoRoot, 'app', '.staging'), fresh: mode === 'staging-fresh' }
  const folder = env['DOOR_SANDBOX_DIR'] || join(repoRoot, 'app', '.sandbox')
  if (mode === 'sandbox') return { environment: 'sandbox', folder, start: 'keep' }
  if (mode === 'sandbox-fresh') return { environment: 'sandbox', folder, start: 'fresh' }
  if (mode === 'sandbox-empty') return { environment: 'sandbox', folder, start: 'empty' }
  if (env['DOOR_SANDBOX_DIR']) return { environment: 'sandbox', folder, start: env['DOOR_SANDBOX_EMPTY'] === '1' ? 'empty' : 'keep' }
  return { environment: 'production' }
}

/** Makes this start's folder: staging's (emptied when fresh), the sandbox's (seeded, made again, or emptied). Refuses the checkout's real data before deleting anything. */
export function prepare(start: Start, repoRoot: string, env: Env, now: Date = new Date()): void {
  if (start.environment === 'staging') {
    const to = refuseRealData(start.folder, repoRoot, 'a staging')
    if (start.fresh) rmSync(to, { recursive: true, force: true })
    mkdirSync(to, { recursive: true })
  } else if (start.environment === 'sandbox') {
    if (start.start === 'empty') {
      const to = refuseRealData(start.folder, repoRoot, 'a sandbox')
      rmSync(to, { recursive: true, force: true })
      mkdirSync(to, { recursive: true })
    } else {
      seedSandbox(start.folder, repoRoot, start.start === 'fresh', now, { discoveryOff: env['DOOR_SANDBOX_DISCOVERY'] === 'off' })
    }
  }
}

/**
 * The server's environment: in staging and the sandbox the data folder is theirs, and the config folders The other
 * door keeps its Drive connection in (drive.json) point inside it too, so the sync sees no connection. HOME and PATH
 * stay yours, so claude is signed in, on your plan; `DOOR_SANDBOX_SIGNED_OUT=1` gives the sandbox a Claude config
 * folder of its own, so it starts signed out and your own login is untouched.
 */
export function serverEnv(start: Start, base: Env): Env {
  if (start.environment === 'production') return base
  const env: Env = { ...base, DOOR_HOME: start.folder, XDG_CONFIG_HOME: join(start.folder, '.config'), APPDATA: join(start.folder, 'appdata') }
  if (start.environment === 'sandbox' && base['DOOR_SANDBOX_SIGNED_OUT'] === '1') env['CLAUDE_CONFIG_DIR'] = join(start.folder, '.claude')
  return env
}

/** `DOOR_SANDBOX_RUN_MS`: how long the sandbox's simulated run takes (a test makes it short). */
export function sandboxRunMs(env: Env): number | undefined {
  const n = Number(env['DOOR_SANDBOX_RUN_MS'])
  return Number.isFinite(n) && n > 0 ? n : undefined
}
