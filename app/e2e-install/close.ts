// Closing a launched app on every path of the install test (#111): a test that failed before its own close left the
// app and its bundled Python running, and on Windows they held the install folder, so the global teardown's
// uninstaller could not remove it ("could not uninstall: …"). The app is asked to quit; one that does not in time,
// or whose close fails, is killed with its children (the server).
import { execFileSync } from 'node:child_process'

export interface Closable {
  close(): Promise<void>
  process(): { pid?: number; exitCode?: number | null; signalCode?: string | null }
}

const exited = (p: ReturnType<Closable['process']>): boolean => (p.exitCode ?? null) !== null || (p.signalCode ?? null) !== null

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
  if (exited(app.process())) return
  let timer: NodeJS.Timeout | undefined
  const closed = await Promise.race([
    app.close().then(() => true, () => false),
    new Promise<boolean>((done) => { timer = setTimeout(() => done(false), timeoutMs) }),
  ])
  clearTimeout(timer)
  if (closed) return
  const pid = app.process().pid
  if (pid === undefined) return
  try {
    kill(pid)
  } catch (e) {
    console.error(`could not kill the app (pid ${pid}): ${e instanceof Error ? e.message : e}`)
  }
}
