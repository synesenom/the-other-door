// The CV photo's file (#605). It is chosen in an open dialog the main process runs; the window gets only a
// one-shot token and the file's name, which `take` turns into the real path for the `save_photo` tool. The
// server checks the bytes and cleans the picture (EXIF and GPS dropped, scaled); this is the quick look.
import { randomUUID } from 'node:crypto'
import { basename, extname } from 'node:path'

export const MAX_PHOTO_BYTES = 10 * 1024 * 1024
export const PHOTO_EXTENSIONS = ['jpg', 'jpeg', 'png']

interface Deps {
  showOpenDialog: (options: Record<string, unknown>) => Promise<{ canceled: boolean; filePaths: string[] }>
  stat: (path: string) => Promise<{ size: number }>
  realpath: (path: string) => Promise<string>
}

const isPicture = (p: string) => PHOTO_EXTENSIONS.includes(extname(p).toLowerCase().slice(1))

export function createPhotoFile(deps: Deps) {
  // One photo at a time: a new pick replaces the last.
  let pending: { token: string; path: string } | null = null
  return {
    async pick(): Promise<{ token: string; name: string } | { canceled: true } | { error: string }> {
      const r = await deps.showOpenDialog({
        title: 'Choose your photo',
        properties: ['openFile'],
        filters: [{ name: 'Pictures', extensions: PHOTO_EXTENSIONS }],
      })
      if (r.canceled || r.filePaths.length === 0) return { canceled: true }
      const chosen = r.filePaths[0]!
      try {
        // The name picked and the file behind it must both be a picture: a link to something else is refused.
        const real = await deps.realpath(chosen)
        if (!isPicture(chosen) || !isPicture(real)) return { error: 'Choose a JPEG or PNG picture.' }
        if ((await deps.stat(real)).size > MAX_PHOTO_BYTES) return { error: 'That picture is over 10 MB.' }
        pending = { token: randomUUID(), path: real }
      } catch {
        return { error: 'That file could not be read.' }
      }
      return { token: pending.token, name: basename(chosen) }
    },
    /** The real path of the picked picture, once. */
    take(token: string): string | null {
      if (!pending || pending.token !== token) return null
      const { path } = pending
      pending = null
      return path
    },
  }
}

export type PhotoFile = ReturnType<typeof createPhotoFile>
