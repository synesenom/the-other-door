// The phone server is a detached process that outlives the app (#77): before an update installs it is
// stopped, so the old code stops answering the phone and no file under the install folder stays held. A
// Tailscale connection (`lasting`) is started again by the new version; a quick tunnel is left stopped
// (its address changes anyway). Best effort: failures are logged and never block the update.
export interface PhoneUpdateDeps {
  call: (tool: string, args?: Record<string, unknown>) => Promise<unknown>
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

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

export async function stopPhoneForUpdate(deps: PhoneUpdateDeps): Promise<void> {
  const ms = deps.timeoutMs ?? 5000
  try {
    await bounded(
      (async () => {
        const status = (await deps.call('phone_status', {})) as { running?: boolean; lasting?: boolean }
        if (!status?.running) return
        await deps.call('phone_stop', {})
        if (status.lasting) deps.fs.write(deps.markerPath)
      })(),
      ms,
    )
  } catch (e) {
    deps.log(`stopping the phone server before an update failed: ${message(e)}`)
  }
}

export async function restorePhoneAfterUpdate(deps: PhoneUpdateDeps): Promise<void> {
  if (!deps.fs.exists(deps.markerPath)) return
  try {
    const out = (await bounded(deps.call('phone_start', { connection: 'tailscale' }), deps.timeoutMs ?? 5000)) as { error?: string; needs?: string } | undefined
    if (out?.error) deps.log(`starting the phone server after an update failed: ${out.error}`)
    else if (out?.needs) deps.log(`starting the phone server after an update needs: ${out.needs}`)
  } catch (e) {
    deps.log(`starting the phone server after an update failed: ${message(e)}`)
  } finally {
    try {
      deps.fs.remove(deps.markerPath)
    } catch (e) {
      deps.log(`removing the phone restart marker failed: ${message(e)}`)
    }
  }
}
