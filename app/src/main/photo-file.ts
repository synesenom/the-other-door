// The CV photo's file (#605). It is chosen in an open dialog the main process runs; the window gets only a
// one-shot token and the file's name, which `take` turns into the real path for the `save_photo` tool. The
// server checks the bytes and cleans the picture (EXIF and GPS dropped, scaled); this is the quick look.
import { basename } from 'node:path'
import { checkPicked, oneShot } from './files'

export const MAX_PHOTO_BYTES = 10 * 1024 * 1024
export const PHOTO_EXTENSIONS = ['jpg', 'jpeg', 'png']

interface Deps {
  showOpenDialog: (options: Record<string, unknown>) => Promise<{ canceled: boolean; filePaths: string[] }>
  stat: (path: string) => Promise<{ size: number }>
  realpath: (path: string) => Promise<string>
}

export function createPhotoFile(deps: Deps) {
  const picked = oneShot()
  return {
    async pick(): Promise<{ token: string; name: string } | { canceled: true } | { error: string }> {
      const r = await deps.showOpenDialog({
        title: 'Choose your photo',
        properties: ['openFile'],
        filters: [{ name: 'Pictures', extensions: PHOTO_EXTENSIONS }],
      })
      if (r.canceled || r.filePaths.length === 0) return { canceled: true }
      const chosen = r.filePaths[0]!
      const checked = await checkPicked(
        chosen,
        { extensions: PHOTO_EXTENSIONS, size: { maxBytes: MAX_PHOTO_BYTES, tooBig: 'That picture is over 10 MB.' }, wrongType: 'Choose a JPEG or PNG picture.' },
        deps,
      )
      if (!checked.ok) return { error: checked.error }
      return { token: picked.put(checked.real), name: basename(chosen) }
    },
    /** The real path of the picked picture, once. */
    take: picked.take,
  }
}

export type PhotoFile = ReturnType<typeof createPhotoFile>
