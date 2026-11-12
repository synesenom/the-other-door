// The one seam of the install test (#639), all of it on the test's side: the installed app is not changed.
// An installed app starts `<bundled python> -s -m door.mcp_server` as soon as it opens, before a test can reach
// its main process (it reads no `-r`, and packaged Electron refuses NODE_OPTIONS' --require). So, right after
// the launch, this patches the main process's child_process.spawn to run the test world's boot.py
// (test/world/boot.py: door's own server with the job boards, the network and Drive answered from the world)
// instead of `-m door.mcp_server` — on the same bundled Python, with the same arguments' cwd and environment
// the app built (the bundled door on PYTHONPATH, the bundled Tectonic first on PATH) — and stops the server
// the app had already started. The app's next call starts it again, through the patch.
import type { ElectronApplication } from '@playwright/test'

/** What the app asked to start, as the patch saw it (written to `<world>/spawned.json`). */
export interface Spawned {
  command: string
  args: string[]
  cwd?: string
  env: Record<string, string>
}

/** Patches the spawn and stops the server already running; returns how many it stopped. */
export function redirectServer(app: ElectronApplication, boot: string, world: string): Promise<number> {
  return app.evaluate(
    (_electron, { boot, world }) => {
      const req = (process as unknown as { mainModule: NodeJS.Module }).mainModule.require
      const cp = req('node:child_process') as typeof import('node:child_process')
      const fs = req('node:fs') as typeof import('node:fs')
      const path = req('node:path') as typeof import('node:path')
      const spawn = cp.spawn
      ;(cp as { spawn: unknown }).spawn = function (this: unknown, command: string, args: string[], options: { cwd?: string; env?: Record<string, string> }) {
        if (Array.isArray(args) && args.includes('door.mcp_server')) {
          fs.writeFileSync(path.join(world, 'spawned.json'), JSON.stringify({ command, args, cwd: options?.cwd, env: options?.env ?? {} }))
          args = ['-s', boot, world]
        }
        return (spawn as (...a: unknown[]) => unknown).call(this, command, args, options)
      }
      const handles = (process as unknown as { _getActiveHandles(): { spawnargs?: string[]; kill?(signal: string): void }[] })._getActiveHandles()
      const running = handles.filter((h) => Array.isArray(h?.spawnargs) && h.spawnargs.includes('door.mcp_server'))
      for (const child of running) child.kill?.('SIGKILL')
      return running.length
    },
    { boot, world },
  )
}
