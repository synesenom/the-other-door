import { describe, expect, it, vi } from 'vitest'
import { checkUrls, createCvSources, LINKEDIN_HINT, MAX_CV_BYTES } from './cv-sources'

function setup(paths: string[], sizes: Record<string, number> = {}) {
  const sizeOf = { ...sizes }
  const showOpenDialog = vi.fn(async () => ({ canceled: false, filePaths: paths }))
  const stat = vi.fn(async (p: string) => ({ size: sizeOf[p] ?? 1000 }))
  const sources = createCvSources({ showOpenDialog, stat })
  return { sources, showOpenDialog, stat, sizeOf }
}

describe('createCvSources', () => {
  it('returns the picked files under opaque, distinct tokens', async () => {
    const { sources } = setup(['/Users/ada/secret/cv.pdf', '/Users/ada/secret/notes.md'])
    const r = await sources.pick()
    expect(r.refused).toEqual([])
    expect(r.files.map((f) => f.name)).toEqual(['cv.pdf', 'notes.md'])
    expect(r.files.map((f) => f.size)).toEqual([1000, 1000])
    const [a, b] = r.files
    expect(a!.token).not.toBe(b!.token)
    expect(JSON.stringify(r)).not.toContain('secret')
  })

  it('takes dropped paths through the same checks, under the same tokens', async () => {
    const { sources } = setup([], { '/a/big.pdf': 26 * 1024 * 1024 })
    const r = await sources.add(['/a/cv.pdf', '/a/photo.png', '/a/big.pdf'])
    expect(r.files.map((f) => f.name)).toEqual(['cv.pdf'])
    expect(r.refused.map((f) => f.name)).toEqual(['photo.png', 'big.pdf'])
    expect(await sources.resolve([r.files[0]!.token])).toEqual({ ok: true, paths: ['/a/cv.pdf'] })
  })

  it('draws a new token for the same file each time', async () => {
    const { sources } = setup(['/a/cv.pdf'])
    const one = await sources.pick()
    const two = await sources.pick()
    expect(one.files[0]!.token).not.toBe(two.files[0]!.token)
  })

  it('refuses another extension, case-insensitively, with a reason', async () => {
    const { sources } = setup(['/a/run.exe', '/a/noext', '/a/CV.PDF', '/a/b.Docx', '/a/c.markdown', '/a/d.txt'])
    const r = await sources.pick()
    expect(r.files.map((f) => f.name)).toEqual(['CV.PDF', 'b.Docx', 'c.markdown', 'd.txt'])
    expect(r.refused.map((x) => x.name)).toEqual(['run.exe', 'noext'])
    expect(r.refused[0]!.reason).toMatch(/PDF, DOCX/)
  })

  it('refuses a file over 25 MB', async () => {
    const { sources } = setup(['/a/big.pdf'], { '/a/big.pdf': MAX_CV_BYTES + 1 })
    const r = await sources.pick()
    expect(r.files).toEqual([])
    expect(r.refused[0]).toMatchObject({ name: 'big.pdf' })
    expect(r.refused[0]!.reason).toMatch(/25 MB/)
  })

  it('refuses a file it cannot read', async () => {
    const showOpenDialog = vi.fn(async () => ({ canceled: false, filePaths: ['/a/gone.pdf'] }))
    const sources = createCvSources({ showOpenDialog, stat: async () => { throw new Error('ENOENT') } })
    const r = await sources.pick()
    expect(r.files).toEqual([])
    expect(r.refused[0]!.name).toBe('gone.pdf')
  })

  it('returns nothing when the dialog is cancelled', async () => {
    const showOpenDialog = vi.fn(async () => ({ canceled: true, filePaths: [] }))
    const sources = createCvSources({ showOpenDialog, stat: async () => ({ size: 1 }) })
    expect(await sources.pick()).toEqual({ files: [], refused: [] })
  })

  it('resolves tokens to paths and rejects an unknown one', async () => {
    const { sources } = setup(['/a/cv.pdf', '/a/b.md'])
    const { files } = await sources.pick()
    const ok = await sources.resolve(files.map((f) => f.token))
    expect(ok).toEqual({ ok: true, paths: ['/a/cv.pdf', '/a/b.md'] })
    const bad = await sources.resolve([files[0]!.token, 'nope'])
    expect(bad.ok).toBe(false)
  })

  it('checks size and extension again when resolving', async () => {
    const { sources, sizeOf } = setup(['/a/cv.pdf'])
    const { files } = await sources.pick()
    sizeOf['/a/cv.pdf'] = MAX_CV_BYTES + 5
    const r = await sources.resolve([files[0]!.token])
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toMatch(/25 MB/)
  })

  it('forgets every token on clear', async () => {
    const { sources } = setup(['/a/cv.pdf'])
    const { files } = await sources.pick()
    sources.clear()
    const r = await sources.resolve([files[0]!.token])
    expect(r.ok).toBe(false)
  })

  it('has no way to read the registry', () => {
    const { sources } = setup([])
    expect(Object.keys(sources).sort()).toEqual(['add', 'clear', 'pick', 'resolve'])
  })
})

describe('checkUrls', () => {
  it('passes http and https', () => {
    expect(checkUrls(['https://a.com/cv', 'http://b.org'])).toEqual({ ok: true })
  })
  it.each(['file:///etc/passwd', 'javascript:alert(1)', 'not a url', 'ftp://x.com'])('refuses %s', (u) => {
    expect(checkUrls([u]).ok).toBe(false)
  })
  it.each(['https://linkedin.com/in/ada', 'https://www.linkedin.com/in/ada/', 'https://dk.linkedin.com/in/ada', 'https://linkedin.com./in/ada', 'https://www.linkedin.com./in/ada'])('refuses LinkedIn %s with the hint', (u) => {
    expect(checkUrls([u])).toEqual({ ok: false, error: LINKEDIN_HINT })
  })
  it('does not mistake a lookalike host for LinkedIn', () => {
    expect(checkUrls(['https://notlinkedin.com/in/x'])).toEqual({ ok: true })
  })
  it('has the hint in words', () => {
    expect(LINKEDIN_HINT).toBe("LinkedIn pages can't be read; save your profile as a PDF (More → Save to PDF) and add that file.")
  })

  describe('a picked path later swapped for a link', () => {
    it('checks the real target at draft time and hands the server that real path', async () => {
      const showOpenDialog = vi.fn(async () => ({ canceled: false, filePaths: ['/a/cv.pdf'] }))
      const stat = vi.fn(async () => ({ size: 1000 }))
      let target = '/a/cv.pdf'
      const realpath = vi.fn(async () => target)
      const sources = createCvSources({ showOpenDialog, stat, realpath })
      const [file] = (await sources.pick()).files
      expect(await sources.resolve([file!.token])).toEqual({ ok: true, paths: ['/a/cv.pdf'] })
      target = '/Users/ada/.ssh/id_ed25519'
      const r = await sources.resolve([file!.token])
      expect(r.ok).toBe(false)
      target = '/Users/ada/Documents/real-cv.pdf'
      expect(await sources.resolve([file!.token])).toEqual({ ok: true, paths: ['/Users/ada/Documents/real-cv.pdf'] })
      expect(stat).toHaveBeenLastCalledWith('/Users/ada/Documents/real-cv.pdf')
    })

    it('refuses a pick whose real target is not a CV file', async () => {
      const sources = createCvSources({
        showOpenDialog: async () => ({ canceled: false, filePaths: ['/a/cv.pdf'] }),
        stat: async () => ({ size: 10 }),
        realpath: async () => '/etc/passwd',
      })
      const r = await sources.pick()
      expect(r.files).toEqual([])
      expect(r.refused.map((x) => x.name)).toEqual(['cv.pdf'])
    })
  })
})
