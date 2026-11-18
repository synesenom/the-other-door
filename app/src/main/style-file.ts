// The CV file: the one a draft last read (Profile → CV's Sources names it), and the CV a style is built from, chosen
// from Profile → CV. The main process runs the open dialog and starts the build itself with the real path (ipc.ts),
// so the window never receives a path, only the file's name. The dialog opens at the CV file while it is still
// there: its path is kept in a small file of the app's own folder (never sent to the window or the server), written
// when a draft answers.
import { basename } from 'node:path'
import { checkPicked } from './files'

export const MAX_STYLE_BYTES = 25 * 1024 * 1024

interface Deps {
  showOpenDialog: (options: Record<string, unknown>) => Promise<{ canceled: boolean; filePaths: string[] }>
  stat: (path: string) => Promise<{ size: number }>
  realpath: (path: string) => Promise<string>
  hintStore: { read(): Promise<string | null>; write(path: string): Promise<void> }
  exists: (path: string) => boolean
}

const STYLE_EXTENSIONS = ['pdf']

export function createStyleFile(deps: Deps) {
  return {
    async choose(): Promise<{ path: string } | { canceled: true } | { error: string }> {
      const hint = await deps.hintStore.read().catch(() => null)
      const r = await deps.showOpenDialog({
        title: 'Choose a CV to copy the style of',
        properties: ['openFile'],
        filters: [{ name: 'CV as a PDF', extensions: STYLE_EXTENSIONS }],
        ...(hint && deps.exists(hint) ? { defaultPath: hint } : {}),
      })
      if (r.canceled || r.filePaths.length === 0) return { canceled: true }
      const chosen = r.filePaths[0]!
      const checked = await checkPicked(
        chosen,
        { extensions: STYLE_EXTENSIONS, size: { maxBytes: MAX_STYLE_BYTES, tooBig: 'That file is over 25 MB.' }, wrongType: 'Choose a CV as a PDF.', unreadable: `${basename(chosen)} could not be read.` },
        deps,
      )
      return checked.ok ? { path: checked.real } : { error: checked.error }
    },
    /** Keep the path of the CV file a draft read: Sources names it, and the dialog opens there. */
    async remember(path: string): Promise<void> {
      try {
        await deps.hintStore.write(path)
      } catch {
        // a convenience: nothing to say when it cannot be kept
      }
    },
    /** The CV file's name (never its path) while it is still there, else null. */
    async name(): Promise<string | null> {
      const hint = await deps.hintStore.read().catch(() => null)
      return hint && deps.exists(hint) ? basename(hint) : null
    },
  }
}

export type StyleFile = ReturnType<typeof createStyleFile>
