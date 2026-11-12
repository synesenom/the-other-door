// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mockDoor } from '../../testing'
import { saveProfile } from './save'
import { existingProfile, freshProfile } from './testing'
import { initialState, toInitArgs, wizardReducer, type WizardState } from './reducer'

const filled = (over: Partial<WizardState> = {}): WizardState => ({
  ...initialState(freshProfile),
  name: 'Ada', email: 'ada@x.dk', location: 'Aarhus', roleTargets: ['Dev'],
  ...over,
})
const names = (h: ReturnType<typeof mockDoor>) => h.call.mock.calls.map((c) => c[0])

describe('saveProfile', () => {
  it('writes the profile, then the CV, then reads the profile back, in that order', async () => {
    const h = mockDoor({ init_profile: { config_path: '/p/config.json' }, save_cv: { cv_path: '/p/cv.md' }, show_profile: existingProfile })
    const state = filled({ cvText: '# Ada\n' })
    const result = await saveProfile(state)
    expect(names(h)).toEqual(['init_profile', 'save_cv', 'show_profile'])
    expect(h.call).toHaveBeenNthCalledWith(1, 'init_profile', toInitArgs(state))
    expect(h.call).toHaveBeenNthCalledWith(2, 'save_cv', { markdown: '# Ada\n' })
    expect(result).toEqual({ ok: true, profile: existingProfile })
  })

  it('does not touch the CV when the step produced no text', async () => {
    const h = mockDoor({ init_profile: {}, show_profile: existingProfile })
    await saveProfile(filled())
    expect(names(h)).toEqual(['init_profile', 'show_profile'])
  })

  it('an init_profile error stops there and says which fields', async () => {
    const h = mockDoor({
      init_profile: () => {
        throw new Error('profile/config.json: role_targets — at least one')
      },
      save_cv: {},
    })
    const result = await saveProfile(filled({ cvText: 'x' }))
    expect(result).toEqual({ ok: false, kind: 'fields', error: 'profile/config.json: role_targets — at least one' })
    expect(names(h)).toEqual(['init_profile'])
  })

  it('a save_cv error is reported as the CV\'s', async () => {
    mockDoor({
      init_profile: {},
      save_cv: () => {
        throw new Error('the CV is empty; nothing was written')
      },
    })
    expect(await saveProfile(filled({ cvText: 'x' }))).toEqual({ ok: false, kind: 'cv', error: 'the CV is empty; nothing was written' })
  })

  it('saves a chosen photo by its token after the CV, and a removal through remove_photo', async () => {
    const h = mockDoor({ init_profile: {}, save_cv: {}, show_profile: existingProfile })
    const result = await saveProfile(filled({ cvText: '# Ada\n', photo: { kind: 'new', token: 't1', name: 'me.jpg' } }))
    expect(names(h)).toEqual(['init_profile', 'save_cv', 'show_profile'])
    expect(window.door.savePhoto).toHaveBeenCalledWith('t1')
    expect(result.ok).toBe(true)
    const gone = mockDoor({ init_profile: {}, remove_photo: { removed: true }, show_profile: existingProfile })
    await saveProfile(filled({ photo: { kind: 'none' } }))
    expect(names(gone)).toEqual(['init_profile', 'remove_photo', 'show_profile'])
  })

  it('a photo the tool refuses is reported as the photo\'s, with the reason', async () => {
    const h = mockDoor({ init_profile: {}, show_profile: existingProfile })
    h.savePhoto.mockResolvedValueOnce({ ok: false, error: 'the picture is too small (50 x 50 px)' })
    expect(await saveProfile(filled({ photo: { kind: 'new', token: 't1', name: 'me.jpg' } }))).toEqual({ ok: false, kind: 'photo', error: 'the picture is too small (50 x 50 px)' })
  })

  it('leaves the photo alone when nothing was chosen', async () => {
    const h = mockDoor({ init_profile: {}, show_profile: existingProfile })
    await saveProfile(filled())
    expect(h.savePhoto).not.toHaveBeenCalled()
    expect(names(h)).not.toContain('remove_photo')
  })

  it('the reducer puts a fields error under its review section', async () => {
    const s = wizardReducer({ ...filled(), step: 'review' }, { type: 'saveFailed', error: 'profile/config.json: role_targets — at least one' })
    expect(s.step).toBe('review')
    expect(s.errors.titles).toEqual(['at least one'])
  })

  describe('the example story', () => {
    const story = { title: 'Halved the close', context: 'c', action: 'a', result: 'r', learning: 'l' }

    it('a kept one is saved after the CV, before the profile is read back', async () => {
      const h = mockDoor({ init_profile: {}, save_cv: {}, save_story: { outcome: 'added' }, show_profile: existingProfile })
      await saveProfile(filled({ cvText: '# Ada\n', story: { values: story, keep: true } }))
      expect(names(h)).toEqual(['init_profile', 'save_cv', 'save_story', 'show_profile'])
      expect(h.call).toHaveBeenCalledWith('save_story', story)
    })

    it('one let go is not saved', async () => {
      const h = mockDoor({ init_profile: {}, show_profile: existingProfile })
      await saveProfile(filled({ story: { values: story, keep: false } }))
      expect(names(h)).toEqual(['init_profile', 'show_profile'])
    })

    it('a refused one says why, the rest saved', async () => {
      mockDoor({ init_profile: {}, save_story: () => { throw new Error('a story titled x is already in the bank') } })
      const result = await saveProfile(filled({ story: { values: story, keep: true } }))
      expect(result).toEqual({ ok: false, kind: 'story', error: 'a story titled x is already in the bank' })
    })
  })
})
