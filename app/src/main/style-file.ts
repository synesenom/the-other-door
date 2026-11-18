// The CV file: the one a draft last read (Profile → CV's Sources names it and replaces it). It is also the one CV a
// style is built from: the main process starts the build itself with the real path (ipc.ts), so the window never
// receives a path, only the file's name. The path is kept in a small file of the app's own folder (never sent to the
// window or the server), written when a draft answers.
import { basename } from 'node:path'
import { checkPicked } from './files'

export const MAX_STYLE_BYTES = 25 * 1024 * 1024

interface Deps {
  stat: (path: string) => Promise<{ size: number }>
  realpath: (path: string) => Promise<string>
  hintStore: { read(): Promise<string | null>; write(path: string): Promise<void> }
  exists: (path: string) => boolean
}

export function createStyleFile(deps: Deps) {
  const kept = async () => {
    const hint = await deps.hintStore.read().catch(() => null)
    return hint && deps.exists(hint) ? hint : null
  }
  return {
    /** The CV file to build a style from: its real path, or why it cannot be used. */
    async current(): Promise<{ path: string } | { error: string }> {
      const file = await kept()
      if (!file) return { error: 'Choose your CV file under Sources first.' }
      const checked = await checkPicked(
        file,
        {
          extensions: ['pdf'],
          size: { maxBytes: MAX_STYLE_BYTES, tooBig: 'Your CV file is over 25 MB.' },
          wrongType: 'Your CV file is not a PDF, so it has no style to copy. Choose a PDF under Sources.',
          unreadable: `${basename(file)} could not be read.`,
        },
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
      const file = await kept()
      return file ? basename(file) : null
    },
  }
}

export type StyleFile = ReturnType<typeof createStyleFile>
