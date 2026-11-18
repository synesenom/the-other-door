// The phone server is a detached process that outlives the app (#77): before an update installs it is
// stopped, so the old code stops answering the phone and no file under the install folder stays held. A
// Tailscale connection (`lasting`) is started again by the new version; a quick tunnel is left stopped
// (its address changes anyway). A CV style build is a detached process too, running the bundled Python for
// minutes: it is stopped as well and reads as failed, the style in use untouched (#215). Best effort: failures
// are logged and never block the update.
export interface PhoneUpdateDeps {
  call: (tool: string, args?: Record<string, unknown>, timeoutMs?: number) => Promise<unknown>
  markerPath: string
  fs: { write(path: string): void; exists(path: string): boolean; remove(path: string): void }
  log: (message: string) => void
  timeoutMs?: number
}

function bounded<T>(work: Promise<T>, ms: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout>
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`no answer in ${ms} ms`)), ms)
  })
  return Promise.race([work, timeout]).finally(() => clearTimeout(timer))
}

// Starting a phone server waits for `door serve` and the connection to answer: as long as the window allows (ipc.ts).
const START_TIMEOUT_MS = 300_000

// Whether a quit may go on, or must first stop the phone server and a style build because it installs a downloaded update.
export function quitStep(state: { installsOnQuit: boolean; stopped: boolean }): 'proceed' | 'stop-then-quit' {
  return state.installsOnQuit && !state.stopped ? 'stop-then-quit' : 'proceed'
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

export async function stopPhoneForUpdate(deps: PhoneUpdateDeps): Promise<void> {
  const ms = deps.timeoutMs ?? 10_000
  try {
    await bounded(
      (async () => {
        const status = (await deps.call('phone_status', {})) as { running?: boolean; lasting?: boolean }
        // Always stop: a quick tunnel that died reads as not running while `door serve` is still alive.
        await deps.call('phone_stop', {})
        if (status?.running && status.lasting) deps.fs.write(deps.markerPath)
      })(),
      ms,
    )
  } catch (e) {
    deps.log(`stopping the phone server before an update failed: ${message(e)}`)
  }
}

// The server's worst case: ending the build (Windows' taskkill, up to 15 s) then waiting for its lock (`style.LOCK_WAIT`,
// 20 s). Longer than the phone's stop.
const STYLE_STOP_TIMEOUT_MS = 45_000

export async function stopStyleBuildForUpdate(deps: PhoneUpdateDeps): Promise<void> {
  const ms = deps.timeoutMs ?? STYLE_STOP_TIMEOUT_MS
  try {
    await bounded(Promise.resolve(deps.call('stop_style_build', {}, ms)), ms)
  } catch (e) {
    deps.log(`stopping the CV style build before an update failed: ${message(e)}`)
  }
}

// What an install waits for: the phone server and a style build stopped, side by side.
export async function stopForUpdate(deps: PhoneUpdateDeps): Promise<void> {
  await Promise.all([stopPhoneForUpdate(deps), stopStyleBuildForUpdate(deps)])
}

async function startTailscale(deps: PhoneUpdateDeps, why: string): Promise<void> {
  try {
    const out = (await deps.call('phone_start', { connection: 'tailscale' }, START_TIMEOUT_MS)) as { error?: string; needs?: string } | undefined
    if (out?.error) deps.log(`starting the phone server ${why} failed: ${out.error}`)
    else if (out?.needs) deps.log(`starting the phone server ${why} needs: ${out.needs}`)
  } catch (e) {
    deps.log(`starting the phone server ${why} failed: ${message(e)}`)
  }
}

export async function restorePhoneAfterUpdate(deps: PhoneUpdateDeps): Promise<void> {
  if (!deps.fs.exists(deps.markerPath)) return
  // Removed first: one try per update, never a retry at every start.
  try {
    deps.fs.remove(deps.markerPath)
  } catch (e) {
    deps.log(`removing the phone restart marker failed: ${message(e)}`)
  }
  await startTailscale(deps, 'after an update')
}

// After a hand install (#109) a phone server of the older version may still be answering. At start, with no update
// marker: stop it, and start it again only on Tailscale (a quick tunnel stays stopped, its address changes anyway).
// A first start after a hand install may wait for the server's cold start and a data migration (DoorServer allows 30 s).
const START_CHECK_MS = 60_000

export async function restoreOutdatedPhone(deps: PhoneUpdateDeps): Promise<void> {
  try {
    const status = (await bounded(deps.call('phone_status', {}), deps.timeoutMs ?? START_CHECK_MS)) as
      | { running?: boolean; outdated?: boolean; connection?: string }
      | undefined
    if (!status?.running || !status.outdated) return
    // `phone_start` replaces an outdated server itself; a quick tunnel is only stopped.
    if (status.connection === 'tailscale') await startTailscale(deps, 'of the older version again')
    else await bounded(deps.call('phone_stop', {}), deps.timeoutMs ?? START_CHECK_MS)
  } catch (e) {
    deps.log(`replacing the phone server of an older version failed: ${message(e)}`)
  }
}
