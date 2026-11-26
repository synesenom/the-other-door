// The phone server is a detached process that outlives the app (#77): before an update installs it is
// stopped, so the old code stops answering the phone and no file under the install folder stays held. A
// quick tunnel's address changes on every start anyway, so nothing starts it again: the phone is set up
// again from Settings. Best effort: failures are logged and never block the update.
export interface PhoneUpdateDeps {
  call: (tool: string, args?: Record<string, unknown>, timeoutMs?: number) => Promise<unknown>
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

// Whether a quit may go on, or must first stop the phone server because it installs a downloaded update.
export function quitStep(state: { installsOnQuit: boolean; stopped: boolean }): 'proceed' | 'stop-then-quit' {
  return state.installsOnQuit && !state.stopped ? 'stop-then-quit' : 'proceed'
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

export async function stopPhoneForUpdate(deps: PhoneUpdateDeps): Promise<void> {
  try {
    // Always stop: a quick tunnel that died reads as not running while `door serve` is still alive.
    await bounded(deps.call('phone_stop', {}), deps.timeoutMs ?? 10_000)
  } catch (e) {
    deps.log(`stopping the phone server before an update failed: ${message(e)}`)
  }
}

// A first start after a hand install may wait for the server's cold start and a data migration (DoorServer allows 30 s).
const START_CHECK_MS = 60_000

// At the app's start (#109): a live server of an older version (a hand install, which stops nothing) answers
// with old code, so it is stopped. `phone_start` replaces an outdated server itself.
export async function stopOutdatedPhoneAtStart(deps: PhoneUpdateDeps): Promise<void> {
  try {
    const status = (await bounded(deps.call('phone_status', {}), deps.timeoutMs ?? START_CHECK_MS)) as { running?: boolean; outdated?: boolean } | undefined
    if (status?.running && status.outdated) await bounded(deps.call('phone_stop', {}), deps.timeoutMs ?? START_CHECK_MS)
  } catch (e) {
    deps.log(`stopping an outdated phone server at start failed: ${message(e)}`)
  }
}
