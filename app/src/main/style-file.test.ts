import { describe, expect, it, vi } from 'vitest'
import { createStyleFile, MAX_STYLE_BYTES } from './style-file'

function setup(path: string | null, opts: { size?: number; real?: string; unreadable?: boolean; hint?: string | null; hintExists?: boolean } = {}) {
  const showOpenDialog = vi.fn(async (_options: Record<string, unknown>) => (path === null ? { canceled: true, filePaths: [] } : { canceled: false, filePaths: [path] }))
  const stat = vi.fn(async () => ({ size: opts.size ?? 1000 }))
  const realpath = vi.fn(async (p: string) => {
    if (opts.unreadable) throw new Error('gone')
    return opts.real ?? p
  })
  let hint: string | null = opts.hint ?? null
  const hintStore = {
    read: vi.fn(async () => hint),
    write: vi.fn(async (p: string) => {
      hint = p
    }),
  }
  const exists = vi.fn((p: string) => (opts.hintExists ?? true) && p === hint)
  return { style: createStyleFile({ showOpenDialog, stat, realpath, hintStore, exists }), showOpenDialog, hintStore }
}

describe('createStyleFile', () => {
  it('names the file when it cannot be resolved', async () => {
    expect(await setup('/a/my cv.pdf', { unreadable: true }).style.choose()).toEqual({ error: 'my cv.pdf could not be read.' })
  })
  it('asks for a PDF and answers the real path', async () => {
    const { style, showOpenDialog } = setup('/Users/ada/my cv.pdf')
    expect(await style.choose()).toEqual({ path: '/Users/ada/my cv.pdf' })
    expect(showOpenDialog.mock.calls[0]![0]).toMatchObject({ properties: ['openFile'], filters: [{ extensions: ['pdf'] }] })
  })
  it('a cancelled dialog chooses nothing', async () => {
    expect(await setup(null).style.choose()).toEqual({ canceled: true })
  })
  it('refuses another type, also behind a link, and a file over 25 MB, with a reason', async () => {
    expect(await setup('/a/cv.docx').style.choose()).toEqual({ error: 'Choose a CV as a PDF.' })
    expect(await setup('/a/cv.pdf', { real: '/a/secret.txt' }).style.choose()).toEqual({ error: 'Choose a CV as a PDF.' })
    expect(await setup('/a/cv.pdf', { size: MAX_STYLE_BYTES + 1 }).style.choose()).toEqual({ error: 'That file is over 25 MB.' })
  })
  it('opens the dialog at the CV the set-up read, while that file is still there', async () => {
    const { style, showOpenDialog } = setup('/a/cv.pdf', { hint: '/Users/ada/cv.pdf' })
    await style.choose()
    expect(showOpenDialog.mock.calls[0]![0]).toMatchObject({ defaultPath: '/Users/ada/cv.pdf' })
  })
  it('opens at the system default once that file is gone', async () => {
    const { style, showOpenDialog } = setup('/a/cv.pdf', { hint: '/Users/ada/cv.pdf', hintExists: false })
    await style.choose()
    expect(showOpenDialog.mock.calls[0]![0]).not.toHaveProperty('defaultPath')
  })
  it('remembers the path it is told, and only a PDF', async () => {
    const { style, hintStore } = setup(null)
    await style.remember('/a/cv.docx')
    expect(hintStore.write).not.toHaveBeenCalled()
    await style.remember('/a/cv.pdf')
    expect(hintStore.write).toHaveBeenCalledWith('/a/cv.pdf')
  })
})
