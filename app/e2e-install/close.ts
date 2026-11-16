// Closing a launched app on every path of the install test (#111): a test that failed before its own close left the
// app and its bundled Python running, and on Windows they held the install folder, so the global teardown's
// uninstaller could not remove it ("could not uninstall: …"). The app is asked to quit; one that does not in time,
// or whose close fails, is killed with its children (the server).
import { execFileSync } from 'node:child_process'

export interface Closable {
  close(): Promise<void>
  process(): { pid?: number; exitCode?: number | null; signalCode?: string | null }
}

/** The app's process, or null when Playwright already disposed the app (its `process()` throws once it closed). */
function processOf(app: Closable): ReturnType<Closable['process']> | null {
  try {
    return app.process()
  } catch {
    return null
  }
}

const exited = (p: ReturnType<Closable['process']> | null): boolean => p === null || (p.exitCode ?? null) !== null || (p.signalCode ?? null) !== null

/** The command that kills a process with its children, or null where killing the process itself is enough. */
export function killTreeCommand(platform: string, pid: number): string[] | null {
  return platform === 'win32' ? ['taskkill', '/PID', String(pid), '/T', '/F'] : null
}

function killTree(pid: number): void {
  const argv = killTreeCommand(process.platform, pid)
  if (argv) execFileSync(argv[0]!, argv.slice(1), { stdio: 'ignore', timeout: 30_000 })
  else process.kill(pid, 'SIGKILL')
}

/** Closes the app; never throws: what is left is killed, and a kill that fails is only logged. */
export async function closeApp(app: Closable, { timeoutMs = 30_000, kill = killTree }: { timeoutMs?: number; kill?: (pid: number) => void } = {}): Promise<void> {
  const before = processOf(app)
  if (exited(before)) return
  let timer: NodeJS.Timeout | undefined
  const closed = await Promise.race([
    app.close().then(() => true, () => false),
    new Promise<boolean>((done) => { timer = setTimeout(() => done(false), timeoutMs) }),
  ])
  clearTimeout(timer)
  if (closed) return
  const pid = (processOf(app) ?? before)?.pid
  if (pid === undefined) return
  try {
    kill(pid)
  } catch (e) {
    console.error(`could not kill the app (pid ${pid}): ${e instanceof Error ? e.message : e}`)
  }
}

/** Every app launched, registered as soon as it started (so a launch that fails later is closed too), all closed at the end. */
export function createTracker(): { track(app: Closable): void; closeAll(options?: Parameters<typeof closeApp>[1]): Promise<void> } {
  const apps = new Set<Closable>()
  return {
    track: (app) => {
      apps.add(app)
    },
    closeAll: async (options) => {
      const open = [...apps]
      apps.clear()
      for (const app of open) await closeApp(app, options)
    },
  }
}

/**
 * The command that kills whatever still runs from the install folder before the uninstaller removes it: a server the
 * app's quit left running (its `before-quit` does not wait for it), Chromium under it, an app no test closed (a crashed
 * worker, a timeout). On Windows by executable path; elsewhere by command line (`pkill -f`, a regex).
 */
export function sweepCommand(platform: string, folder: string): string[] {
  if (platform === 'win32') {
    const prefix = `${folder.replace(/\\+$/, '')}\\`.replace(/'/g, "''")
    return ['powershell', '-NoProfile', '-Command',
      `Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith('${prefix}', 'OrdinalIgnoreCase') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }`]
  }
  return ['pkill', '-KILL', '-f', `^${folder.replace(/\/+$/, '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/`]
}
