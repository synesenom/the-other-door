// The CV file: the one a draft last read (Profile → CV's Sources names it and replaces it). The window never receives
// its path, only its name. The path is kept in a small file of the app's own folder (never sent to the window or the
// server), written when a draft answers.
import { basename } from 'node:path'

interface Deps {
  hintStore: { read(): Promise<string | null>; write(path: string): Promise<void> }
  exists: (path: string) => boolean
}

export function createCvFile(deps: Deps) {
  return {
    /** Keep the path of the CV file a draft read: Sources names it. */
    async remember(path: string): Promise<void> {
      try {
        await deps.hintStore.write(path)
      } catch {
        // a convenience: nothing to say when it cannot be kept
      }
    },
    /** The CV file's name (never its path) while it is still there, else null. */
    async name(): Promise<string | null> {
      const file = await deps.hintStore.read().catch(() => null)
      return file && deps.exists(file) ? basename(file) : null
    },
  }
}

export type CvFile = ReturnType<typeof createCvFile>
