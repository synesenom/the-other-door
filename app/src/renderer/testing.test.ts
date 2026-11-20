// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mockDoor } from './testing'

describe('mockDoor', () => {
  it('stands in for the CV draft surface', async () => {
    const h = mockDoor({}, { actions: { 'pick-cv-files': async () => ({ files: [], refused: [] }), 'cv-sources-clear': async () => undefined } })
    expect(await window.door.invoke('pick-cv-files')).toEqual({ files: [], refused: [] })
    expect(await window.door.call('draft_cv', { sources: [] }, undefined, [])).toMatchObject({ ok: false })
    await window.door.invoke('cv-sources-clear')
    expect(h.actions['pick-cv-files']).toHaveBeenCalledTimes(1)
    expect(h.call).toHaveBeenCalledTimes(1)
    expect(h.actions['cv-sources-clear']).toHaveBeenCalledTimes(1)
  })

  it('answers a call with tokens from a draft_cv handler', async () => {
    mockDoor({ draft_cv: (a: Record<string, unknown>) => ({ got: a }) })
    expect(await window.door.call('draft_cv', { sources: ['https://a.com'] }, undefined, ['t'])).toEqual({ ok: true, data: { got: { sources: ['https://a.com'], tokens: ['t'] } } })
  })
})

describe('mockDoor actions', () => {
  it('answers a known action and refuses an unknown one with one stated error', async () => {
    mockDoor({}, { actions: { 'pick-cv-files': async () => ({ files: [], refused: [] }) } })
    expect(await window.door.invoke('pick-cv-files')).toEqual({ files: [], refused: [] })
    await expect(window.door.invoke('show-home')).rejects.toThrow('unknown action show-home') // no answer given: refused
    await expect((window.door as unknown as { invoke(a: string): Promise<unknown> }).invoke('no-such-action')).rejects.toThrow('unknown action no-such-action')
  })

  it('takes an answer for an action from the test', async () => {
    const m = mockDoor({}, { actions: { 'cv-file': async () => 'my cv.pdf' } })
    expect(await window.door.invoke('cv-file')).toBe('my cv.pdf')
    m.actions['pick-photo'].mockResolvedValueOnce({ token: 't', name: 'me.jpg' })
    expect(await window.door.invoke('pick-photo')).toEqual({ token: 't', name: 'me.jpg' })
    expect(m.invoke).toHaveBeenCalledWith('pick-photo')
  })

  it('answers a pushed event to its listeners, and an unknown event with a no-op unsubscribe', () => {
    const m = mockDoor({})
    const seen: unknown[] = []
    const off = window.door.on('open', (t) => seen.push(t))
    m.pushOpen({ screen: 'matches' })
    off()
    m.pushOpen({ screen: 'matches', newOnly: true })
    expect(seen).toEqual([{ screen: 'matches' }])
    const none = (window.door as unknown as { on(e: string, cb: () => void): () => void }).on('no-such-event', () => undefined)
    expect(() => none()).not.toThrow()
  })
})
