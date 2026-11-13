import { describe, expect, it } from 'vitest'
import {
  canRunFirst,
  claudeLogin,
  claudeMissing,
  claudeReady,
  discoveryFor,
  discoveryOff,
  initialState,
  reviewProblem,
  routeErrors,
  stillUnfound,
  todoCount,
  toInitArgs,
  wizardReducer,
  type Basics,
  type WizardState, ownTitles, isLinkedIn, photoPolicy
} from './reducer'
import { cvState, doctorReport, existingProfile, freshProfile, savedConfig } from './testing'

const fresh = () => initialState(freshProfile)
const redo = () => initialState(existingProfile)
const filled = (over: Partial<WizardState> = {}): WizardState => ({ ...fresh(), name: 'Ada', email: 'ada@x.dk', location: 'Aarhus', roleTargets: ['Dev'], ...over })
const basics = (over: Partial<Basics> = {}): Basics => ({ name: 'Ada', email: 'ada@x.dk', location: 'Aarhus', languages: ['English', 'Danish'], remote: 'hybrid', missing: [], ...over })
const title = (t: string, recommended = true) => ({ title: t, reason: `why ${t}`, recommended })

describe('the three screens', () => {
  it('a fresh home opens at the sources, with sensible defaults', () => {
    const s = fresh()
    expect(s.mode).toBe('fresh')
    expect(s.step).toBe('sources')
    expect(s.languages).toEqual(['English'])
    expect(s.remote).toBe('hybrid')
    expect(s.discovery).toEqual({})
  })

  it('a saved profile is a redo of the same screens, prefilled', () => {
    const s = redo()
    expect(s.mode).toBe('redo')
    expect(s.step).toBe('sources')
    expect(s.name).toBe(savedConfig.name)
    expect(s.keywordsState).toBe('config')
    expect(s.titles).toEqual([{ title: 'Data Scientist', reason: 'In your profile', recommended: true }])
  })

  it('goes sources, reading, review and no further', () => {
    let s = fresh()
    s = wizardReducer(s, { type: 'next' })
    expect(s.step).toBe('reading')
    s = wizardReducer(s, { type: 'next' })
    expect(s.step).toBe('review')
    expect(wizardReducer(s, { type: 'next' }).step).toBe('review')
  })

  it('back from the review goes past reading, which runs by itself', () => {
    expect(wizardReducer({ ...fresh(), step: 'review' }, { type: 'back' }).step).toBe('sources')
    expect(wizardReducer({ ...fresh(), step: 'reading' }, { type: 'back' }).step).toBe('sources')
    expect(wizardReducer(fresh(), { type: 'back' }).step).toBe('sources')
  })
})

describe('the sources', () => {
  it('keeps files and pages, each once', () => {
    const f = { token: 't', name: 'cv.pdf', size: 1 }
    let s = wizardReducer(fresh(), { type: 'addFiles', files: [f] })
    s = wizardReducer(s, { type: 'addFiles', files: [{ ...f, token: 'other' }] })
    expect(s.files).toEqual([f])
    expect(wizardReducer(s, { type: 'dropFile', token: 't' }).files).toEqual([])
    s = wizardReducer(s, { type: 'addUrl', url: 'https://a.dev' })
    s = wizardReducer(s, { type: 'addUrl', url: 'https://a.dev' })
    expect(s.urls).toEqual(['https://a.dev'])
    expect(wizardReducer(s, { type: 'dropUrl', url: 'https://a.dev' }).urls).toEqual([])
  })

  it('Claude is ready when it is installed and signed in', () => {
    expect(claudeReady(doctorReport('ok'))).toBe(true)
    expect(claudeReady(doctorReport('out'))).toBe(false)
    const missing = { ok: false, checks: [{ name: 'claude CLI', status: 'missing', required: true, detail: '' }] }
    expect(claudeMissing(missing)).toBe(true)
    expect(claudeReady(missing)).toBe(false)
  })
})

describe('what reading finds', () => {
  it('fills everything and asks nothing when the CV says it all', () => {
    const s = wizardReducer(fresh(), { type: 'basics', basics: basics() })
    expect([s.name, s.email, s.location, s.languages]).toEqual(['Ada', 'ada@x.dk', 'Aarhus', ['English', 'Danish']])
    expect(s.missing).toEqual([])
  })

  it('what was not found is named until it is filled in', () => {
    let s = wizardReducer(fresh(), { type: 'basics', basics: basics({ name: null, email: null, location: null, missing: ['name', 'email', 'location'] }) })
    s = wizardReducer(s, { type: 'titles', titles: [] })
    expect(stillUnfound(s)).toEqual(['your name', 'your email', 'your city', 'job titles'])
    s = wizardReducer(s, { type: 'set', field: 'name', value: 'Ada' })
    s = wizardReducer(s, { type: 'set', field: 'email', value: 'nope' })
    expect(stillUnfound(s)).toEqual(['your email', 'your city', 'job titles'])
    s = wizardReducer(s, { type: 'set', field: 'email', value: 'ada@x.dk' })
    s = wizardReducer(s, { type: 'set', field: 'location', value: 'Aarhus' })
    s = wizardReducer(s, { type: 'addTitle', title: 'Lead' })
    expect(stillUnfound(s)).toEqual([])
  })

  it('keeps the place the wizard does not cover for the review', () => {
    const s = wizardReducer(fresh(), { type: 'basics', basics: basics({ location: null, unsupported_location: 'Berlin', missing: ['location'] }) })
    expect(s.unsupportedLocation).toBe('Berlin')
    expect(s.missing).toEqual(['location'])
  })

  it('a redo keeps its answers and only fills the gaps', () => {
    const s = wizardReducer(redo(), { type: 'basics', basics: basics({ name: 'Someone Else', location: 'Copenhagen', remote: 'no' }) })
    expect(s.name).toBe(savedConfig.name)
    expect(s.location).toBe(savedConfig.location)
    expect(s.languages).toEqual(savedConfig.languages)
    expect(s.remote).toBe('hybrid')
    expect(s.missing).toEqual([])
  })

  it('pre-selects the recommended titles', () => {
    const s = wizardReducer(fresh(), { type: 'titles', titles: [title('Lead'), title('Quant', false)] })
    expect(s.titles.map((t) => t.title)).toEqual(['Lead', 'Quant'])
    expect(s.roleTargets).toEqual(['Lead'])
    expect(s.missing).toEqual([])
  })

  it('a redo keeps its picks and adds the recommended new ones', () => {
    const s = wizardReducer(redo(), { type: 'titles', titles: [title('Data Scientist'), title('Lead'), title('Quant', false)] })
    expect(s.roleTargets).toEqual(['Data Scientist', 'Lead'])
  })

  it('keeps what Claude could not do for the review, each step its own line, gone when the step is done again', () => {
    let s = wizardReducer(fresh(), { type: 'basics', basics: basics({ warning: 'usage limit' }) })
    s = wizardReducer(s, { type: 'titles', titles: [], warning: 'overloaded' })
    s = wizardReducer(s, { type: 'skipKeywords', warning: 'quota' })
    expect(s.warnings).toEqual({ basics: 'usage limit', titles: 'overloaded', terms: 'quota' })
    s = wizardReducer(s, { type: 'basics', basics: basics() })
    s = wizardReducer(s, { type: 'titles', titles: [title('Lead')] })
    s = wizardReducer(s, { type: 'keywords', keywords: ['lead'], topicTerms: [] })
    expect(s.warnings).toEqual({})
  })

  it('no titles at all is remembered, and basics coming later keeps that', () => {
    let s = wizardReducer(fresh(), { type: 'titles', titles: [] })
    expect(s.missing).toEqual(['titles'])
    s = wizardReducer(s, { type: 'basics', basics: basics({ name: null, missing: ['name'] }) })
    expect(s.missing).toEqual(['name', 'titles'])
  })
})

describe('titles and chips', () => {
  it('toggling a title picks and unpicks it, and keeps it on the list', () => {
    let s = wizardReducer(fresh(), { type: 'titles', titles: [title('Lead'), title('Quant', false)] })
    s = wizardReducer(s, { type: 'toggleTitle', title: 'Quant' })
    expect(s.roleTargets).toEqual(['Lead', 'Quant'])
    s = wizardReducer(s, { type: 'toggleTitle', title: 'Lead' })
    expect(s.roleTargets).toEqual(['Quant'])
    expect(s.titles).toHaveLength(2)
  })

  it('adding a title picks it, once, trimmed, as the user\'s own and droppable', () => {
    let s = wizardReducer(fresh(), { type: 'addTitle', title: '  Actuary ' })
    s = wizardReducer(s, { type: 'addTitle', title: 'actuary' })
    s = wizardReducer(s, { type: 'addTitle', title: '   ' })
    expect(s.roleTargets).toEqual(['Actuary'])
    expect(s.titles).toEqual([])
    expect(ownTitles(s)).toEqual(['Actuary'])
    s = wizardReducer(s, { type: 'dropTitle', title: 'Actuary' })
    expect(s.roleTargets).toEqual([])
  })

  it('adding a suggested title ticks the suggestion instead of making a pill', () => {
    let s = wizardReducer(fresh(), { type: 'titles', titles: [{ title: 'Lead', reason: 'r', recommended: false }] })
    s = wizardReducer(s, { type: 'addTitle', title: 'lead' })
    expect(s.roleTargets).toEqual(['Lead'])
    expect(ownTitles(s)).toEqual([])
  })

  it('adds and drops chips, trimmed, without empties or case-insensitive duplicates', () => {
    let s = wizardReducer(fresh(), { type: 'add', list: 'keywords', value: ' ml ' })
    s = wizardReducer(s, { type: 'add', list: 'keywords', value: 'ML' })
    s = wizardReducer(s, { type: 'add', list: 'keywords', value: ' ' })
    expect(s.keywords).toEqual(['ml'])
    expect(wizardReducer(s, { type: 'drop', list: 'keywords', value: 'ml' }).keywords).toEqual([])
  })

  it('takes the proposed terms; skipping falls back to the titles', () => {
    let s = wizardReducer(filled(), { type: 'keywords', keywords: ['ml'], topicTerms: ['data'] })
    expect(s.keywordsState).toBe('proposed')
    expect(toInitArgs(s)['search_keywords']).toEqual(['ml'])
    s = wizardReducer(s, { type: 'skipKeywords' })
    expect(s.keywordsState).toBe('skipped')
    expect(toInitArgs(s)['search_keywords']).toEqual(['Dev'])
    expect(toInitArgs(s)['topic_terms']).toEqual([])
  })
})

describe('the review', () => {
  it('names what is still needed before Save', () => {
    const own = { ...freshProfile, cv: cvState({ exists: true, is_example: false }) }
    expect(reviewProblem(filled(), own)).toBeNull()
    expect(reviewProblem(filled({ name: ' ' }), own)).toMatch(/name/)
    expect(reviewProblem(filled({ email: 'nope' }), own)).toMatch(/email/)
    expect(reviewProblem(filled({ location: '' }), own)).toMatch(/city/)
    expect(reviewProblem(filled({ languages: [] }), own)).toMatch(/language/)
    expect(reviewProblem(filled({ roleTargets: [] }), own)).toMatch(/title/)
  })
  it('needs a CV of the user\'s, also when setting up again', () => {
    const example = { ...freshProfile, cv: cvState({ exists: true, is_example: true }) }
    expect(reviewProblem(filled(), freshProfile)).toMatch(/CV/)
    expect(reviewProblem(filled(), example)).toMatch(/CV/)
    expect(reviewProblem(filled({ cvText: '  ' }), freshProfile)).toMatch(/CV/)
    expect(reviewProblem(filled({ cvText: '# Ada' }), freshProfile)).toBeNull()
    expect(reviewProblem(filled({ mode: 'redo' }), example)).toMatch(/CV/)
  })
})

describe('discovery', () => {
  it('every source of the city is off until ticked', () => {
    const s = filled({ location: 'Aarhus' })
    expect(discoveryFor(s).map(({ key, label, on }) => ({ key, label, on }))).toEqual([{ key: 'linkedin_discovery', label: 'LinkedIn', on: false }, { key: 'hellowork_discovery', label: 'HelloWork', on: false }])
    expect(discoveryFor(s)[0].disclaimer).toMatch(/LinkedIn disclaimer text/)  // the server's text rides along
    const on = wizardReducer(s, { type: 'discovery', key: 'hellowork_discovery', value: true })
    expect(discoveryFor(on).map((d) => d.on)).toEqual([false, true])
  })

  it('a city in no known country asks about the worldwide ones', () => {
    expect(discoveryFor(filled({ location: 'Berlin' })).map((d) => d.key)).toEqual(['linkedin_discovery'])
  })

  it('a redo keeps the saved answers', () => {
    const s = initialState({ ...existingProfile, config: { ...savedConfig, linkedin_discovery: true } })
    expect(discoveryFor(s).map((d) => d.on)).toEqual([true, false])
  })
})

describe('preferences', () => {
  it('start empty on a fresh home and from the saved text on a redo', () => {
    expect(fresh().preferences).toBe('')
    const profile = { ...existingProfile, config: { ...existingProfile.config!, preferences: 'robotics' } }
    expect(initialState(profile).preferences).toBe('robotics')
    expect(redo().preferences).toBe('')
  })

  it('are kept as typed until Save', () => {
    const s = wizardReducer(filled(), { type: 'set', field: 'preferences', value: ' medical; not banking ' })
    expect(s.preferences).toBe(' medical; not banking ')
  })

  it('go to init_profile in other, trimmed, when there is some', () => {
    const s = wizardReducer(filled(), { type: 'set', field: 'preferences', value: ' medical; not banking ' })
    expect((toInitArgs(s)['other'] as Record<string, unknown>)['preferences']).toBe('medical; not banking')
  })

  it('are left out on a first set-up when empty, and sent empty on a redo to clear them', () => {
    expect(toInitArgs(filled())['other']).not.toHaveProperty('preferences')
    expect((toInitArgs(redo())['other'] as Record<string, unknown>)['preferences']).toBe('')
  })
})

describe('toInitArgs', () => {
  it('a fresh home sends every key, so nothing of the example config survives', () => {
    const args = toInitArgs(filled({ keywords: ['ml'], topicTerms: ['data'], remote: 'yes' }))
    expect(args).toEqual({
      name: 'Ada', email: 'ada@x.dk', location: 'Aarhus', languages: ['English'], role_targets: ['Dev'],
      search_keywords: ['ml'], topic_terms: ['data'], remote: 'yes', exclude_companies: [], exclude_keywords: [],
      other: { linkedin_discovery: false, hellowork_discovery: false },
    })
  })

  it('sends an answer for each discovery source, ticked or not', () => {
    const s = wizardReducer(filled(), { type: 'discovery', key: 'linkedin_discovery', value: true })
    expect(toInitArgs(s)['other']).toEqual({ linkedin_discovery: true, hellowork_discovery: false })
  })

  it('a redo leaves the exclusions alone: they are the Profile screen\'s', () => {
    const args = toInitArgs(redo())
    expect(args).not.toHaveProperty('exclude_companies')
    expect(args).not.toHaveProperty('exclude_keywords')
  })

  it('sends enrich_sources in other only when there are some', () => {
    expect(toInitArgs(filled())['other']).not.toHaveProperty('enrich_sources')
    expect(toInitArgs(filled({ enrichSources: ['https://a.dev'] }))['other']).toMatchObject({ enrich_sources: ['https://a.dev'] })
  })
})

describe('routeErrors', () => {
  it('sends each line to the section that owns the field; unknown fields stay at the top', () => {
    expect(
      routeErrors(
        ['profile/config.json: name — required', 'profile/config.json: role_targets — at least one', 'profile/config.json: topic_terms.0 — not text', 'profile/config.json: linkedin_discovery — a boolean', 'profile/config.json: min_score — too low'].join('\n'),
      ),
    ).toEqual({ you: ['required'], titles: ['at least one'], terms: ['not text'], employers: ['a boolean'], review: ['min_score: too low'] })
  })

  it('a text with no config line stays whole at the top', () => {
    expect(routeErrors('it broke')).toEqual({ review: ['it broke'] })
  })

  it('saveFailed stays on the review with the messages, and an edit clears its section', () => {
    let s = wizardReducer({ ...filled(), step: 'review' }, { type: 'saveFailed', error: 'profile/config.json: name — required' })
    expect(s.step).toBe('review')
    expect(s.errors).toEqual({ you: ['required'] })
    s = wizardReducer(s, { type: 'set', field: 'name', value: 'Ada' })
    expect(s.errors).toEqual({})
  })
})

describe('canRunFirst', () => {
  const profile = { ...existingProfile }
  const example = { ...existingProfile, cv: { ...existingProfile.cv, is_example: true } }

  it('needs the user\'s CV and Claude', () => {
    expect(canRunFirst(filled(), profile, doctorReport('ok'))).toBe(true)
    expect(canRunFirst(filled(), example, doctorReport('ok'))).toBe(false)
    expect(canRunFirst(filled(), profile, doctorReport('out'))).toBe(false)
    expect(canRunFirst(filled(), profile, null)).toBe(false)
  })

  it('counts a CV the wizard just wrote', () => {
    expect(canRunFirst(filled({ cvText: '# Ada' }), example, doctorReport('ok'))).toBe(true)
  })

  it('in the sandbox only the CV counts', () => {
    expect(canRunFirst(filled(), profile, doctorReport('out'), true)).toBe(true)
    expect(canRunFirst(filled(), example, doctorReport('out'), true)).toBe(false)
  })

  it('claudeLogin reads the account from the doctor details', () => {
    expect(claudeLogin(doctorReport('ok'))).toEqual({ connected: true, email: 'ada@example.com', plan: 'max' })
    expect(claudeLogin(doctorReport('out'))).toEqual({ connected: false })
    expect(claudeLogin(null)).toEqual({ connected: false })
  })
})

describe('the draft', () => {
  const done = { type: 'draftDone' as const, markdown: '# Ada\n', sources: [] }

  it('puts the markdown in the CV text and keeps what it learned', () => {
    const s = wizardReducer(fresh(), { ...done, urls: [] })
    expect(s.cvText).toBe('# Ada\n')
    expect(s.cvDraft).toEqual({ sources: [] })
  })

  it('adds the public pages to enrichSources once, never LinkedIn', () => {
    const s = wizardReducer(fresh(), { ...done, urls: ['https://a.dev', 'https://a.dev', 'https://www.linkedin.com/in/a'] })
    expect(s.enrichSources).toEqual(['https://a.dev'])
  })

  it('a LinkedIn address written with a trailing dot is LinkedIn too', () => {
    expect(['https://linkedin.com./in/a', 'https://www.linkedin.com./in/a', 'https://dk.linkedin.com/in/a'].every(isLinkedIn)).toBe(true)
    expect(['https://notlinkedin.com/a', 'https://a.dev/linkedin.com', 'nope'].some(isLinkedIn)).toBe(false)
    const s = wizardReducer(fresh(), { ...done, urls: ['https://a.dev', 'https://linkedin.com./in/a'] })
    expect(s.enrichSources).toEqual(['https://a.dev'])
  })

  it('a second draft replaces the pages of the first', () => {
    let s = wizardReducer(fresh(), { ...done, urls: ['https://a.dev'] })
    s = wizardReducer(s, { ...done, urls: ['https://b.dev'] })
    expect(s.enrichSources).toEqual(['https://b.dev'])
  })

  it('todoCount counts each gap, also two on one line, and only the whole word', () => {
    expect(todoCount('a\nTODO b\nc TODO\n')).toBe(2)
    expect(todoCount('TODO, TODO\n')).toBe(2)
    expect(todoCount('MASTODON TODOS\n')).toBe(0)
  })
})

describe('the CV photo', () => {
  it('asks only where the city\'s country has a photo optional or expected', () => {
    expect(photoPolicy(freshProfile.options, 'Aarhus')).toBe('optional')
    expect(photoPolicy(freshProfile.options, ' aarhus ')).toBe('optional')
    expect(photoPolicy(freshProfile.options, 'Atlantis')).toBe('no')
    expect(photoPolicy({ ...freshProfile.options, cities: [{ name: 'London', country: 'gb', boards: [], cv: { photo: 'no', date_of_birth: false, max_pages: 2, date_format: 'DD/MM/YYYY' } }] }, 'London')).toBe('no')
  })

  it('starts as it is, takes a picked picture and a removal, and drops an unsaved pick on removal', () => {
    expect(fresh().photo).toEqual({ kind: 'keep' })
    const picked = wizardReducer(fresh(), { type: 'photo', choice: { kind: 'new', token: 't1', name: 'me.jpg' } })
    expect(picked.photo).toEqual({ kind: 'new', token: 't1', name: 'me.jpg' })
    expect(wizardReducer(picked, { type: 'photo', choice: { kind: 'keep' } }).photo).toEqual({ kind: 'keep' })
  })

  it('a refused photo is said under the photo, and choosing again clears it', () => {
    const failed = wizardReducer({ ...fresh(), step: 'review' }, { type: 'photoFailed', error: 'the picture is too small' })
    expect(failed.errors.photo).toEqual(['the picture is too small'])
    expect(wizardReducer(failed, { type: 'photo', choice: { kind: 'none' } }).errors.photo).toBeUndefined()
  })

  it('the photo is not an init_profile argument: it is saved by its own tool', () => {
    const args = toInitArgs({ ...filled(), photo: { kind: 'new', token: 't1', name: 'me.jpg' } })
    expect(JSON.stringify(args)).not.toContain('photo')
  })
})

describe('the example story (the story bank shown once, at onboarding)', () => {
  const story = { title: 'Halved the close', context: 'A slow close.', action: 'Rebuilt it.', result: 'Two days.', learning: '' }

  it('starts without one; a drafted one is kept by default, and can be edited or let go', () => {
    expect(fresh().story).toBeNull()
    let s = wizardReducer(fresh(), { type: 'storyDrafted', story })
    expect(s.story).toEqual({ values: story, keep: true })
    s = wizardReducer(s, { type: 'story', values: { ...story, learning: 'Ask first.' } })
    expect(s.story?.values.learning).toBe('Ask first.')
    s = wizardReducer(s, { type: 'keepStory', keep: false })
    expect(s.story?.keep).toBe(false)
  })

  it('a kept story needs every part filled in before Save; one let go does not', () => {
    const s = wizardReducer(filled({ cvText: '# Ada' }), { type: 'storyDrafted', story })
    expect(reviewProblem(s, freshProfile)).toBe('Fill in the Learning of your story, or untick it.')
    expect(reviewProblem(wizardReducer(s, { type: 'keepStory', keep: false }), freshProfile)).toBeNull()
    expect(reviewProblem(wizardReducer(s, { type: 'story', values: { ...story, learning: 'Ask first.' } }), freshProfile)).toBeNull()
  })

  it('a refused story is said under it, and goes at the next edit', () => {
    let s = wizardReducer(filled(), { type: 'storyDrafted', story })
    s = wizardReducer(s, { type: 'storyFailed', error: 'a story titled x is already in the bank' })
    expect(s.errors.story).toEqual(['a story titled x is already in the bank'])
    expect(s.step).toBe('review')
    s = wizardReducer(s, { type: 'story', values: { ...story, title: 'Other' } })
    expect(s.errors.story).toBeUndefined()
  })
})

describe('discoveryOff, the sources a first run could remind about', () => {
  const withConfig = (over: Record<string, unknown>) => ({ ...existingProfile, config: { ...savedConfig, ...over } })

  it("names the sources serving the profile's city when every one is off", () => {
    expect(discoveryOff(withConfig({ location: 'Aarhus', linkedin_discovery: false, hellowork_discovery: false })).map((d) => d.label)).toEqual(['LinkedIn', 'HelloWork'])
  })

  it('counts a source never chosen as off', () => {
    expect(discoveryOff(withConfig({ location: 'Aarhus', linkedin_discovery: false, hellowork_discovery: undefined })).map((d) => d.label)).toEqual(['LinkedIn', 'HelloWork'])
  })

  it('names none once one of them is on', () => {
    expect(discoveryOff(withConfig({ location: 'Aarhus', linkedin_discovery: false, hellowork_discovery: true }))).toEqual([])
  })

  it('names none without a config, and the worldwide ones for a city in no known country', () => {
    expect(discoveryOff(freshProfile)).toEqual([])
    expect(discoveryOff(withConfig({ location: 'Nowhere', linkedin_discovery: false })).map((d) => d.label)).toEqual(['LinkedIn'])
  })
})
