// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mockDoor } from './testing'

describe('mockDoor', () => {
  it('stands in for the CV draft surface', async () => {
    const h = mockDoor({})
    expect(await window.door.pickCvFiles()).toEqual({ files: [], refused: [] })
    expect(await window.door.draftCv({ files: [], urls: [] })).toMatchObject({ ok: false })
    await window.door.clearCvSources()
    expect(h.pickCvFiles).toHaveBeenCalledTimes(1)
    expect(h.draftCv).toHaveBeenCalledTimes(1)
    expect(h.clearCvSources).toHaveBeenCalledTimes(1)
  })

  it('answers draftCv from a draft_cv handler', async () => {
    mockDoor({ draft_cv: (a: Record<string, unknown>) => ({ got: a }) })
    expect(await window.door.draftCv({ files: ['t'], urls: ['https://a.com'] })).toEqual({ ok: true, data: { got: { files: ['t'], urls: ['https://a.com'] } } })
  })
})
