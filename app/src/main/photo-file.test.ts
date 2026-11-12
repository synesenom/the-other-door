import { describe, expect, it, vi } from 'vitest'
import { createPhotoFile, MAX_PHOTO_BYTES } from './photo-file'

function setup(path: string | null, size = 1000, real?: string) {
  const showOpenDialog = vi.fn(async (_options: Record<string, unknown>) => (path === null ? { canceled: true, filePaths: [] } : { canceled: false, filePaths: [path] }))
  const stat = vi.fn(async () => ({ size }))
  const realpath = vi.fn(async (p: string) => real ?? p)
  return { photo: createPhotoFile({ showOpenDialog, stat, realpath }), showOpenDialog, stat }
}

describe('createPhotoFile', () => {
  it('offers a JPEG or PNG filter and returns a token and a name, never the path', async () => {
    const { photo, showOpenDialog } = setup('/Users/ada/secret/me.JPG')
    const r = await photo.pick()
    expect(r).toMatchObject({ name: 'me.JPG' })
    expect(JSON.stringify(r)).not.toContain('secret')
    expect(showOpenDialog.mock.calls[0]![0]).toMatchObject({ properties: ['openFile'], filters: [{ extensions: ['jpg', 'jpeg', 'png'] }] })
  })

  it('a cancelled dialog picks nothing', async () => {
    expect(await setup(null).photo.pick()).toEqual({ canceled: true })
  })

  it('refuses another type, also behind a link, and a file that is too big, with a reason', async () => {
    expect(await setup('/a/cv.pdf').photo.pick()).toEqual({ error: 'Choose a JPEG or PNG picture.' })
    expect(await setup('/a/me.jpg', 10, '/a/secret.txt').photo.pick()).toEqual({ error: 'Choose a JPEG or PNG picture.' })
    expect(await setup('/a/me.png', MAX_PHOTO_BYTES + 1).photo.pick()).toEqual({ error: 'That picture is over 10 MB.' })
  })

  it('hands the real path over once, for the token it gave out', async () => {
    const { photo } = setup('/a/me.png')
    const r = (await photo.pick()) as { token: string }
    expect(photo.take('nope')).toBeNull()
    expect(photo.take(r.token)).toBe('/a/me.png')
    expect(photo.take(r.token)).toBeNull()
  })

  it('a new pick replaces the last', async () => {
    const { photo } = setup('/a/me.png')
    const one = (await photo.pick()) as { token: string }
    const two = (await photo.pick()) as { token: string }
    expect(photo.take(one.token)).toBeNull()
    expect(photo.take(two.token)).toBe('/a/me.png')
  })
})
