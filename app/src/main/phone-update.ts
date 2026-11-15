// The phone server is a detached process that outlives the app (#77): before an update installs it is
// stopped, so the old code stops answering the phone and no file under the install folder stays held. A
// Tailscale connection (`lasting`) is started again by the new version; a quick tunnel is left stopped
// (its address changes anyway). Best effort: failures are logged and never block the update.
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

// Whether a quit may go on, or must first stop the phone server because it installs a downloaded update.
export function quitStep(state: { installsOnQuit: boolean; phoneStopped: boolean }): 'proceed' | 'stop-then-quit' {
  return state.installsOnQuit && !state.phoneStopped ? 'stop-then-quit' : 'proceed'
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

export async function restorePhoneAfterUpdate(deps: PhoneUpdateDeps): Promise<void> {
  if (!deps.fs.exists(deps.markerPath)) return
  // Removed first: one try per update, never a retry at every start.
  try {
    deps.fs.remove(deps.markerPath)
  } catch (e) {
    deps.log(`removing the phone restart marker failed: ${message(e)}`)
  }
  try {
    const out = (await deps.call('phone_start', { connection: 'tailscale' }, START_TIMEOUT_MS)) as { error?: string; needs?: string } | undefined
    if (out?.error) deps.log(`starting the phone server after an update failed: ${out.error}`)
    else if (out?.needs) deps.log(`starting the phone server after an update needs: ${out.needs}`)
  } catch (e) {
    deps.log(`starting the phone server after an update failed: ${message(e)}`)
  }
}
