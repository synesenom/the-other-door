import { describe, expect, it, vi } from 'vitest'
import { createCvFile } from './cv-file'

function setup(opts: { hint?: string | null; hintExists?: boolean } = {}) {
  let hint: string | null = opts.hint ?? null
  const hintStore = {
    read: vi.fn(async () => hint),
    write: vi.fn(async (p: string) => {
      hint = p
    }),
  }
  const exists = vi.fn((p: string) => (opts.hintExists ?? true) && p === hint)
  return { cv: createCvFile({ hintStore, exists }), hintStore }
}

describe('createCvFile', () => {
  it('remembers the CV file it is told, of any kind', async () => {
    const { cv, hintStore } = setup()
    await cv.remember('/a/cv.docx')
    expect(hintStore.write).toHaveBeenCalledWith('/a/cv.docx')
  })
  it('names the remembered CV file while it is there, by its name only', async () => {
    expect(await setup({ hint: '/Users/ada/Documents/my cv.pdf' }).cv.name()).toBe('my cv.pdf')
    expect(await setup({ hint: '/Users/ada/cv.pdf', hintExists: false }).cv.name()).toBeNull()
    expect(await setup().cv.name()).toBeNull()
  })
  it('says nothing when the path cannot be kept', async () => {
    const hintStore = { read: async () => null, write: async () => { throw new Error('read-only') } }
    await expect(createCvFile({ hintStore, exists: () => true }).remember('/a/cv.pdf')).resolves.toBeUndefined()
  })
})
