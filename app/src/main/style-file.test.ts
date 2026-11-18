import { describe, expect, it, vi } from 'vitest'
import { createStyleFile, MAX_STYLE_BYTES } from './style-file'

function setup(opts: { size?: number; real?: string; unreadable?: boolean; hint?: string | null; hintExists?: boolean } = {}) {
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
  return { style: createStyleFile({ stat, realpath, hintStore, exists }), hintStore }
}

describe('createStyleFile', () => {
  it('the CV file, a PDF, is the one a style is built from: its real path', async () => {
    expect(await setup({ hint: '/Users/ada/my cv.pdf' }).style.current()).toEqual({ path: '/Users/ada/my cv.pdf' })
  })
  it('with no CV file, or one gone, asks for one under Sources', async () => {
    expect(await setup().style.current()).toEqual({ error: 'Choose your CV file under Sources first.' })
    expect(await setup({ hint: '/a/cv.pdf', hintExists: false }).style.current()).toEqual({ error: 'Choose your CV file under Sources first.' })
  })
  it('refuses a CV file that is not a PDF, also behind a link, one over 25 MB, and one it cannot read, with a reason', async () => {
    const notPdf = 'Your CV file is not a PDF, so it has no style to copy. Choose a PDF under Sources.'
    expect(await setup({ hint: '/a/cv.docx' }).style.current()).toEqual({ error: notPdf })
    expect(await setup({ hint: '/a/cv.pdf', real: '/a/secret.txt' }).style.current()).toEqual({ error: notPdf })
    expect(await setup({ hint: '/a/cv.pdf', size: MAX_STYLE_BYTES + 1 }).style.current()).toEqual({ error: 'Your CV file is over 25 MB.' })
    expect(await setup({ hint: '/a/my cv.pdf', unreadable: true }).style.current()).toEqual({ error: 'my cv.pdf could not be read.' })
  })
  it('remembers the CV file it is told, of any kind', async () => {
    const { style, hintStore } = setup()
    await style.remember('/a/cv.docx')
    expect(hintStore.write).toHaveBeenCalledWith('/a/cv.docx')
  })
  it('names the remembered CV file while it is there, by its name only', async () => {
    expect(await setup({ hint: '/Users/ada/Documents/my cv.pdf' }).style.name()).toBe('my cv.pdf')
    expect(await setup({ hint: '/Users/ada/cv.pdf', hintExists: false }).style.name()).toBeNull()
    expect(await setup().style.name()).toBeNull()
  })
})
