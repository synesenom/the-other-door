// The CV a style is built from, chosen from Profile → CV. The main process runs the open dialog and starts the
// build itself with the real path (ipc.ts), so the window never names or receives a path. The dialog opens at the
// CV the set-up read, when that file is still there: its path is kept in a small file of the app's own folder
// (never sent to the window or the server), written when the draft answers.
import { basename, extname } from 'node:path'

export const MAX_STYLE_BYTES = 25 * 1024 * 1024

interface Deps {
  showOpenDialog: (options: Record<string, unknown>) => Promise<{ canceled: boolean; filePaths: string[] }>
  stat: (path: string) => Promise<{ size: number }>
  realpath: (path: string) => Promise<string>
  hintStore: { read(): Promise<string | null>; write(path: string): Promise<void> }
  exists: (path: string) => boolean
}

const isPdf = (p: string) => extname(p).toLowerCase() === '.pdf'

export function createStyleFile(deps: Deps) {
  return {
    async choose(): Promise<{ path: string } | { canceled: true } | { error: string }> {
      const hint = await deps.hintStore.read().catch(() => null)
      const r = await deps.showOpenDialog({
        title: 'Choose a CV to copy the style of',
        properties: ['openFile'],
        filters: [{ name: 'CV as a PDF', extensions: ['pdf'] }],
        ...(hint && deps.exists(hint) ? { defaultPath: hint } : {}),
      })
      if (r.canceled || r.filePaths.length === 0) return { canceled: true }
      const chosen = r.filePaths[0]!
      try {
        // The name picked and the file behind it must both be a PDF: a link to something else is refused.
        const real = await deps.realpath(chosen)
        if (!isPdf(chosen) || !isPdf(real)) return { error: 'Choose a CV as a PDF.' }
        if ((await deps.stat(real)).size > MAX_STYLE_BYTES) return { error: 'That file is over 25 MB.' }
        return { path: real }
      } catch {
        return { error: `${basename(chosen)} could not be read.` }
      }
    },
    /** Keep the path of the CV the set-up read, to open the dialog there. */
    async remember(path: string): Promise<void> {
      if (!isPdf(path)) return
      try {
        await deps.hintStore.write(path)
      } catch {
        // a convenience: nothing to say when it cannot be kept
      }
    },
  }
}

export type StyleFile = ReturnType<typeof createStyleFile>
