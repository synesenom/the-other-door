// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mockDoor } from './testing'

describe('mockDoor', () => {
  it('stands in for the CV draft surface', async () => {
    const h = mockDoor({})
    expect(await window.door.pickCvFiles()).toEqual({ files: [], refused: [] })
    expect(await window.door.call('draft_cv', { sources: [] }, undefined, [])).toMatchObject({ ok: false })
    await window.door.clearCvSources()
    expect(h.pickCvFiles).toHaveBeenCalledTimes(1)
    expect(h.call).toHaveBeenCalledTimes(1)
    expect(h.clearCvSources).toHaveBeenCalledTimes(1)
  })

  it('answers a call with tokens from a draft_cv handler', async () => {
    mockDoor({ draft_cv: (a: Record<string, unknown>) => ({ got: a }) })
    expect(await window.door.call('draft_cv', { sources: ['https://a.com'] }, undefined, ['t'])).toEqual({ ok: true, data: { got: { sources: ['https://a.com'], tokens: ['t'] } } })
  })
})
