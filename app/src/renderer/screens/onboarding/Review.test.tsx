// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../../testing'
import { basename, cvOverview, Review, TERMS_DEBOUNCE_MS } from './Review'
import { Profile } from '../Profile'
import { formSections } from '../profile-form/FormSections'
import { cvState, existingProfile, fields, freshProfile, Host } from './testing'
import type { ShowProfile, WizardState } from './reducer'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

const answers: Partial<WizardState> = {
  step: 'review', name: 'Ada', email: 'ada@x.dk', location: 'Aarhus', languages: ['English'], roleTargets: ['Lead'],
  keywords: ['lead'], topicTerms: ['data'], cvText: '# Ada\n',
}
let seen: WizardState
function setup(start: Partial<WizardState> = answers, handlers: Record<string, unknown> = {}, profile: ShowProfile = freshProfile, before?: (h: ReturnType<typeof mockDoor>) => void) {
  const h = mockDoor({ init_profile: {}, save_cv: {}, show_profile: existingProfile, keywords: { keywords: ['new'], topic_terms: ['t'] }, ...handlers })
  before?.(h)
  const onSaved = vi.fn()
  render(
    <Host profile={profile} start={start}>
      {(state, dispatch) => {
        seen = state
        return <Review state={state} profile={profile} dispatch={dispatch} onSaved={onSaved} />
      }}
    </Host>,
  )
  return { ...h, onSaved }
}
const part = (name: string) => screen.getByRole('region', { name })
const addTitle = (title: string) => {
  const box = within(part('What to look for')).getByLabelText('Role targets')
  fireEvent.change(box, { target: { value: title } })
  fireEvent.keyDown(box, { key: 'Enter' })
}
const dropTitle = (title: string) => fireEvent.click(within(part('What to look for')).getByRole('button', { name: `Remove ${title}` }))

describe('Review, the CV photo', () => {
  it('asks for a photo where the city\'s country has one optional, and holds the pick until Save', async () => {
    const h = setup(answers, { save_photo: { photo_path: '/p/photo.jpg' } })
    h.actions['pick-photo'].mockResolvedValueOnce({ token: 't1', name: 'portrait.jpg' })
    await userEvent.click(within(part('About you')).getByRole('button', { name: 'Choose a photo…' }))
    expect(await screen.findByText('portrait.jpg')).toBeInTheDocument()
    expect(seen.photo).toEqual({ kind: 'new', token: 't1', name: 'portrait.jpg' })
    expect(h.call).not.toHaveBeenCalledWith('save_photo', expect.anything(), undefined, expect.anything())
    await userEvent.click(screen.getByRole('button', { name: 'Save and start searching' }))
    await waitFor(() => expect(h.call).toHaveBeenCalledWith('save_photo', {}, undefined, ['t1']))
  })

  it('says nothing about a photo for a city whose country wants none, or an unknown city', () => {
    const noPhoto = { ...freshProfile, options: { ...freshProfile.options, cities: [{ name: 'London', country: 'gb', boards: [], cv: { photo: 'no' as const, date_of_birth: false, max_pages: 2, date_format: 'DD/MM/YYYY' } }] } }
    setup({ ...answers, location: 'London' }, {}, noPhoto)
    expect(screen.queryByRole('button', { name: /photo/i })).toBeNull()
  })

  it('a refused picture is said under the photo and the wizard stays', async () => {
    const h = setup({ ...answers, photo: { kind: 'new', token: 't1', name: 'tiny.png' } }, {
      save_photo: () => {
      throw new Error('the picture is too small (50 x 50 px)')
    },
    })
    await userEvent.click(screen.getByRole('button', { name: 'Save and start searching' }))
    expect(await within(part('About you')).findByText(/too small/)).toBeInTheDocument()
    expect(h.onSaved).not.toHaveBeenCalled()
  })

  it('Remove drops a pick that was not saved', async () => {
    setup({ ...answers, photo: { kind: 'new', token: 't1', name: 'me.png' } })
    await userEvent.click(within(part('About you')).getByRole('button', { name: 'Remove' }))
    expect(seen.photo).toEqual({ kind: 'keep' })
  })

  it('a photo already kept is shown, and Remove marks it for removal on Save', async () => {
    const kept = { ...existingProfile, photo: { exists: true, path: '/p/profile/photo.jpg' } }
    setup({ ...answers }, {}, kept)
    expect(within(part('About you')).getByRole('img', { name: 'Your photo' })).toBeInTheDocument()
    await userEvent.click(within(part('About you')).getByRole('button', { name: 'Remove' }))
    expect(seen.photo).toEqual({ kind: 'none' })
  })
})

describe('Review', () => {
  it('says what could not be found, and lets go only once it is filled in', async () => {
    setup({ ...answers, name: '', location: '', missing: ['name', 'location'] })
    expect(screen.getByText(/These could not be found in your sources: your name, your city/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save and start searching' })).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Name'), 'Ada')
    await userEvent.selectOptions(screen.getByLabelText('City'), 'Aarhus')
    expect(screen.queryByText(/could not be found/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Save and start searching' })).toBeEnabled()
  })

  it('says nothing about what was found', () => {
    setup()
    expect(screen.queryByText(/could not be found/)).toBeNull()
  })

  it('names the place it does not cover, until a city is chosen', async () => {
    setup({ ...answers, location: '', unsupportedLocation: 'Berlin', missing: ['location'] })
    expect(screen.getByText(/Your CV says Berlin/)).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('City'), 'Aarhus')
    expect(screen.queryByText(/Your CV says Berlin/)).toBeNull()
  })

  it('holds everything inferred, editable in place', async () => {
    setup()
    expect(screen.getByLabelText('Name')).toHaveValue('Ada')
    expect(screen.getByLabelText('Email')).toHaveValue('ada@x.dk')
    expect(screen.getByLabelText('City')).toHaveValue('Aarhus')
    expect(screen.getByRole('radio', { name: 'Hybrid' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'English' })).toBeChecked()
    await userEvent.clear(screen.getByLabelText('Name'))
    await userEvent.type(screen.getByLabelText('Name'), 'Ada L')
    expect(seen.name).toBe('Ada L')
  })

  it('the titles are chips, the recommended ones picked, and take the user\'s own', async () => {
    setup()
    const search = within(part('What to look for'))
    expect(search.getByRole('list', { name: 'Role targets, chosen' })).toHaveTextContent('Lead')
    expect(search.queryByText('Quant')).toBeNull()
    await userEvent.type(search.getByLabelText('Role targets'), 'Actuary{Enter}')
    expect(seen.roleTargets).toEqual(['Lead', 'Actuary'])
    await userEvent.click(search.getByRole('button', { name: 'Remove Actuary' }))
    expect(seen.roleTargets).toEqual(['Lead'])
  })

  it('has an optional What matters to you part: a text area with the example, held until Save', async () => {
    const h = setup()
    const preferences = within(part('What to look for'))
    expect(preferences.getByRole('button', { name: 'About What matters to you' })).toBeInTheDocument()
    const box = preferences.getByRole('textbox', { name: 'What matters to you' })
    expect(box.tagName).toBe('TEXTAREA')
    expect(box).toHaveValue('')
    await userEvent.type(box, 'robotics, no banking')
    expect(seen.preferences).toBe('robotics, no banking')
    expect(h.call).not.toHaveBeenCalledWith('init_profile', expect.anything())
    await userEvent.click(screen.getByRole('button', { name: 'Save and start searching' }))
    await waitFor(() => expect(h.call).toHaveBeenCalledWith('init_profile', expect.objectContaining({ other: expect.objectContaining({ preferences: 'robotics, no banking' }) })))
  })

  it('changing the titles proposes the terms again, debounced, and holds Save until then', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const h = setup()
    addTitle('Quant')
    dropTitle('Lead')
    expect(screen.getByRole('button', { name: 'Save and start searching' })).toBeDisabled()
    expect(h.call).not.toHaveBeenCalledWith('keywords', expect.anything())
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TERMS_DEBOUNCE_MS + 10)
    })
    expect(h.call.mock.calls.filter((c) => c[0] === 'keywords')).toEqual([['keywords', { role_targets: ['Quant'], languages: ['English'] }]])
    await waitFor(() => expect(seen.keywords).toEqual(['new']))
    expect(screen.getByRole('button', { name: 'Save and start searching' })).toBeEnabled()
  })

  it('going back to the same titles asks nothing', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const h = setup()
    dropTitle('Lead')
    addTitle('Lead')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TERMS_DEBOUNCE_MS + 10)
    })
    expect(h.call).not.toHaveBeenCalledWith('keywords', expect.anything())
  })

  it('a failed proposal says nothing: the titles stand in', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    setup(answers, { keywords: () => { throw new Error('quota') } })
    addTitle('Quant')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TERMS_DEBOUNCE_MS + 10)
    })
    await waitFor(() => expect(seen.keywords).toEqual([]))
    expect(screen.queryByText(/quota/)).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('says what Claude could not do while reading, each where it belongs', () => {
    setup({ ...answers, warnings: { basics: 'usage limit', titles: 'overloaded' } })
    expect(within(part('About you')).getByText('Claude could not read your details: usage limit')).toBeInTheDocument()
    expect(within(part('What to look for')).getByText('Claude could not suggest titles: overloaded')).toBeInTheDocument()
  })

  it('every title unticked while new terms are on their way: Save asks for a title, and the late terms are dropped', async () => {
    let answer: (v: unknown) => void = () => undefined
    vi.useFakeTimers({ shouldAdvanceTime: true })
    setup(answers, { keywords: () => new Promise((r) => { answer = r }) })
    addTitle('Quant')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TERMS_DEBOUNCE_MS + 10)
    })
    expect(screen.getByText('Choosing search terms for your titles…')).toBeInTheDocument()
    dropTitle('Lead')
    dropTitle('Quant')
    expect(screen.getByText('Choose at least one title.')).toBeInTheDocument()
    await act(async () => answer({ keywords: ['late'], topic_terms: [] }))
    expect(seen.keywords).toEqual(['lead'])
  })

  it('the CV names a file with no text, and is editable', async () => {
    setup({ ...answers, cvText: '# Ada\nTODO phone\n', cvDraft: { sources: [{ source: '/x/scan.pdf', kind: 'file', chars: 0 }] } })
    expect(screen.getByText(/scan.pdf: no text found/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('switch', { name: 'Preview' }))
    fireEvent.change(screen.getByLabelText('Your CV'), { target: { value: '# New' } })
    expect(seen.cvText).toBe('# New')
  })

  it('shows a CV formatted first, and the switch keeps what was typed', async () => {
    setup({ ...answers, cvText: '# Ada\n' })
    expect(screen.getByRole('switch', { name: 'Preview' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('heading', { name: 'Ada' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Your CV in Markdown')).toBeNull()
    await userEvent.click(screen.getByRole('switch', { name: 'Preview' }))
    expect(screen.getByLabelText('Your CV')).toHaveValue('# Ada\n')
    await userEvent.click(screen.getByRole('switch', { name: 'Preview' }))
    expect(screen.getByRole('heading', { name: 'Ada' })).toBeInTheDocument()
  })

  it('marks each gap in the preview, and a marker selects that gap in the text box', async () => {
    const cvText = '# Ada\n\n**Phone:** TODO\n\n- MSc, TODO year\n'
    setup({ ...answers, cvText })
    const marks = screen.getAllByRole('button', { name: 'to fill in' })
    expect(marks).toHaveLength(2)
    expect(screen.queryByText(/TODO/)).toBeNull()
    await userEvent.click(marks[1]!)
    const box = screen.getByLabelText<HTMLTextAreaElement>('Your CV')
    expect(box).toHaveFocus()
    expect(cvText.slice(box.selectionStart, box.selectionEnd)).toBe('TODO')
    expect(box.selectionStart).toBe(cvText.lastIndexOf('TODO'))
  })

  it('a gap filled in is gone from the preview and the count', async () => {
    setup({ ...answers, cvText: '# Ada\n\nPhone: TODO\n' })
    expect(screen.getByText('1 thing to fill in')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'to fill in' }))
    fireEvent.change(screen.getByLabelText('Your CV'), { target: { value: '# Ada\n\nPhone: 12345\n' } })
    await userEvent.click(screen.getByRole('switch', { name: 'Preview' }))
    expect(screen.queryByRole('button', { name: 'to fill in' })).toBeNull()
    expect(screen.getByText('Ready')).toBeInTheDocument()
  })

  it('switching to the text box by hand selects nothing', async () => {
    setup({ ...answers, cvText: '# Ada\n\nPhone: TODO\n' })
    await userEvent.click(screen.getByRole('switch', { name: 'Preview' }))
    expect(screen.getByLabelText('Your CV')).not.toHaveFocus()
  })

  it('a preview of a CV emptied in the box says there is nothing yet', async () => {
    setup({ ...answers, cvText: '# Ada\n' })
    await userEvent.click(screen.getByRole('switch', { name: 'Preview' }))
    fireEvent.change(screen.getByLabelText('Your CV'), { target: { value: '' } })
    await userEvent.click(screen.getByRole('switch', { name: 'Preview' }))
    expect(screen.getByText('Nothing here yet.')).toBeInTheDocument()
  })

  it('with no CV yet, opens on the text box', () => {
    setup({ ...answers, cvText: null })
    expect(screen.getByRole('switch', { name: 'Preview' })).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByLabelText('Your CV')).toBeInTheDocument()
  })

  it('every discovery source of the city is unticked, with the terms notice', async () => {
    setup()
    const employers = within(part('Where to find employers'))
    expect(employers.getByRole('checkbox', { name: 'LinkedIn' })).not.toBeChecked()
    expect(employers.getByRole('checkbox', { name: 'HelloWork' })).not.toBeChecked()
    expect(employers.getByText(/LinkedIn disclaimer text: its terms ask for no scrapers/)).toBeInTheDocument()
    expect(employers.getByText(/HelloWork disclaimer text: its terms ask for no bots/)).toBeInTheDocument()
    expect(employers.queryByText(/Their terms forbid automated access/)).toBeNull()
  })

  it('with no titles, has no empty list before the box', () => {
    setup({ ...answers, roleTargets: [] })
    expect(within(part('What to look for')).queryByRole('list', { name: 'Role targets, chosen' })).toBeNull()
    expect(within(part('What to look for')).getByRole('textbox', { name: 'Role targets' })).toBeInTheDocument()
  })

  it('opens the legal disclaimer in place, and the answers stay', async () => {
    setup()
    await userEvent.click(screen.getByRole('button', { name: 'legal disclaimer' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Legal disclaimer' }))
    expect(dialog.getByRole('heading', { name: 'Your data' })).toBeInTheDocument()
    await userEvent.click(dialog.getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByLabelText('Name')).toHaveValue('Ada')
  })

  it('Save writes both answers, ticked and not, and hands back the profile', async () => {
    const h = setup()
    await userEvent.click(within(part('Where to find employers')).getByRole('checkbox', { name: 'HelloWork' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save and start searching' }))
    await waitFor(() => expect(h.onSaved).toHaveBeenCalledWith(existingProfile))
    expect(h.call).toHaveBeenCalledWith('init_profile', expect.objectContaining({ other: { linkedin_discovery: false, hellowork_discovery: true } }))
  })

  it('nothing is written before Save', () => {
    const h = setup()
    expect(h.call).not.toHaveBeenCalled()
  })

  it('Save waits for what is missing, and says what', () => {
    setup({ ...answers, roleTargets: [] })
    expect(screen.getByRole('button', { name: 'Save and start searching' })).toBeDisabled()
    expect(screen.getByText('Choose at least one title.')).toBeInTheDocument()
  })

  it('a refused Save stays here with each line under its section, a refused search term in the general alert', async () => {
    setup(answers, { init_profile: () => { throw new Error('profile/config.json: name — too odd\nprofile/config.json: search_keywords — bad') } })
    await userEvent.click(screen.getByRole('button', { name: 'Save and start searching' }))
    expect(await within(part('About you')).findByRole('alert')).toHaveTextContent('too odd')
    expect(screen.getAllByRole('alert').map((a) => a.textContent).join(' ')).toContain('search_keywords: bad')
  })

  it('a failed CV save says the answers are saved', async () => {
    setup({ ...answers, cvText: 'x' }, { save_cv: () => { throw new Error('disk full') } })
    await userEvent.click(screen.getByRole('button', { name: 'Save and start searching' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Your answers are saved, but the CV was not: disk full')
  })

  it('a profile that cannot be read back after a good Save is not called an unsaved CV', async () => {
    setup({ ...answers, cvText: 'x' }, { show_profile: () => { throw new Error('took too long') } })
    await userEvent.click(screen.getByRole('button', { name: 'Save and start searching' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Your answers and CV are saved, but they could not be read back: took too long')
    expect(screen.queryByText(/the CV was not/)).toBeNull()
  })

  it('a redo saves without starting a search', () => {
    setup(answers, {}, existingProfile)
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
  })

  it('a first setup with no CV waits for one, with the box open and staying open while it is typed', () => {
    setup({ ...answers, cvText: null })
    expect(screen.getByRole('button', { name: 'Save and start searching' })).toBeDisabled()
    expect(screen.getByText(/Your CV is needed/)).toBeInTheDocument()
    const box = screen.getByLabelText('Your CV')
    expect(box.closest('details')).toHaveAttribute('open')
    fireEvent.change(box, { target: { value: '# Ada' } })
    expect(screen.getByRole('button', { name: 'Save and start searching' })).toBeEnabled()
    expect(box.closest('details')).toHaveAttribute('open')
  })

  it('cvOverview says what happens to the CV', () => {
    const state = { cvText: null } as WizardState
    expect(cvOverview({ cvText: 'a\nb\n' } as WizardState, freshProfile)).toBe('Ready')
    expect(cvOverview({ cvText: 'a\nTODO b\n' } as WizardState, freshProfile)).toBe('1 thing to fill in')
    expect(cvOverview({ cvText: 'TODO a\nTODO b\n' } as WizardState, freshProfile)).toBe('2 things to fill in')
    expect(cvOverview(state, existingProfile)).toBe('Kept as it is')
    expect(cvOverview(state, { ...freshProfile, cv: cvState({ exists: true, is_example: true }) })).toBe('Still the example CV')
    expect(cvOverview(state, freshProfile)).toBe('No CV yet')
  })

  it('basename keeps a web address whole', () => {
    expect(basename('/a/b/cv.pdf')).toBe('cv.pdf')
    expect(basename('C:\\a\\cv.pdf')).toBe('cv.pdf')
    expect(basename('https://a.dev/x')).toBe('https://a.dev/x')
  })
})

describe('Review, the example story', () => {
  const story = { title: 'Halved the close', context: 'A slow close.', action: 'Rebuilt it.', result: 'Two days.', learning: '' }
  const withStory = { ...answers, story: { values: story, keep: true } }

  it('shows the story bank with one story from the CV, kept, its empty part to fill in before Save', async () => {
    const h = setup(withStory, { save_story: { outcome: 'added' } })
    const bank = part('Stories')
    expect(within(bank).getByText(/A story tells what was behind it/)).toBeInTheDocument()
    expect(within(bank).getByRole('checkbox', { name: 'Keep this story' })).toBeChecked()
    expect(within(bank).getByLabelText('Context')).toHaveValue('A slow close.')
    expect(screen.getByRole('button', { name: 'Save and start searching' })).toBeDisabled()
    expect(screen.getByText('Fill in the Learning of your story, or untick it.')).toBeInTheDocument()
    await userEvent.type(within(bank).getByLabelText('Learning'), 'Ask the people who do it.')
    await userEvent.click(screen.getByRole('button', { name: 'Save and start searching' }))
    await waitFor(() => expect(h.call).toHaveBeenCalledWith('save_story', { ...story, learning: 'Ask the people who do it.' }))
  })

  it('unticked, its fields go and nothing is saved', async () => {
    const h = setup(withStory)
    await userEvent.click(within(part('Stories')).getByRole('checkbox', { name: 'Keep this story' }))
    expect(within(part('Stories')).queryByLabelText('Context')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Save and start searching' }))
    await waitFor(() => expect(h.onSaved).toHaveBeenCalled())
    expect(h.call.mock.calls.map((c) => c[0])).not.toContain('save_story')
  })

  it('without one, no story bank part', () => {
    setup()
    expect(screen.queryByRole('region', { name: 'Stories' })).toBeNull()
  })
})

describe('Review and Profile, one form', () => {
  const headings = () => screen.getAllByRole('heading', { level: 2 }).filter((h) => h.closest('section.part') && !h.closest('.cv-preview')).map((h) => h.textContent)
  const NO_STORIES = { list_stories: { exists: false, stories: [] }, cv_style_sample: { png_base64: 'PNG', own_cv: true } }

  it('show the same part names in the same order, the review fewer of them', async () => {
    const profile = { ...existingProfile, config: { ...existingProfile.config, location: 'Aarhus', preferences: '', languages: ['English'] } }
    mockDoor({ show_profile: profile, ...NO_STORIES })
    render(<Profile onSaved={() => {}} onDraft={() => {}} />)
    await screen.findByRole('region', { name: 'About you' })
    const inProfile = headings()
    cleanup()
    setup({ ...answers, story: null }, {}, profile)
    const inReview = headings().filter((h) => h !== 'Where to find employers')
    expect(inReview).toEqual(['About you', 'What to look for'])
    expect(inProfile.filter((h) => inReview.includes(h))).toEqual(inReview)
    // the CV part is Profile's, under its name
    expect(screen.getByText('Master CV', { selector: 'summary span' })).toBeInTheDocument()
    expect(headings()).toContain('Where to find employers')
  })

  it('the names come from the one layout', () => {
    setup()
    const names = formSections(fields, new Set(['name', 'role_targets'])).map(({ section }) => section.label)
    for (const name of names) expect(part(name)).toBeInTheDocument()
  })

  it('ask the same things the same way', async () => {
    const profile = { ...existingProfile, config: { ...existingProfile.config, location: 'Aarhus', languages: ['English'] } }
    mockDoor({ show_profile: profile, ...NO_STORIES })
    render(<Profile onSaved={() => {}} onDraft={() => {}} />)
    await screen.findByRole('region', { name: 'About you' })
    const labels = (root: HTMLElement) => ['Name', 'Email', 'City', 'Role targets', 'What matters to you'].map((l) => within(root).getByLabelText(l).tagName)
    const radios = (root: HTMLElement) => within(root).getAllByRole('radio').map((r) => r.parentElement!.textContent)
    const inProfile = { labels: labels(document.body), radios: radios(part('About you')), languages: within(part('About you')).getByText('Languages of the job ads') !== null }
    cleanup()
    setup({ ...answers }, {}, profile)
    expect({ labels: labels(document.body), radios: radios(part('About you')), languages: within(part('About you')).getByText('Languages of the job ads') !== null }).toEqual(inProfile)
  })

  it('show no search terms part', () => {
    setup()
    expect(screen.queryByText(/Search terms|Title terms/)).toBeNull()
    expect(screen.queryByRole('region', { name: 'Search' })).toBeNull()
  })
})
