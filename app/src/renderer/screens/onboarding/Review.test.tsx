// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../../testing'
import { basename, cvOverview, Review, TERMS_DEBOUNCE_MS } from './Review'
import { cvState, existingProfile, freshProfile, Host } from './testing'
import type { ShowProfile, WizardState } from './reducer'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

const answers: Partial<WizardState> = {
  step: 'review', name: 'Ada', email: 'ada@x.dk', location: 'Aarhus', languages: ['English'], roleTargets: ['Lead'],
  titles: [{ title: 'Lead', reason: 'you led a team', recommended: true }, { title: 'Quant', reason: 'maths', recommended: false }],
  keywords: ['lead'], topicTerms: ['data'], keywordsState: 'proposed', cvText: '# Ada\n',
}
let seen: WizardState
function setup(start: Partial<WizardState> = answers, handlers: Record<string, unknown> = {}, profile: ShowProfile = freshProfile) {
  const h = mockDoor({ init_profile: {}, save_cv: {}, show_profile: existingProfile, keywords: { keywords: ['new'], topic_terms: ['t'] }, ...handlers })
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

describe('Review, the CV photo', () => {
  it('asks for a photo where the city\'s country has one optional, and holds the pick until Save', async () => {
    const h = setup()
    h.pickPhoto.mockResolvedValueOnce({ token: 't1', name: 'portrait.jpg' })
    await userEvent.click(within(part('You')).getByRole('button', { name: 'Choose a photo…' }))
    expect(await screen.findByText('portrait.jpg')).toBeInTheDocument()
    expect(seen.photo).toEqual({ kind: 'new', token: 't1', name: 'portrait.jpg' })
    expect(h.savePhoto).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Save and start searching' }))
    await waitFor(() => expect(h.savePhoto).toHaveBeenCalledWith('t1'))
  })

  it('says nothing about a photo for a city whose country wants none, or an unknown city', () => {
    const noPhoto = { ...freshProfile, options: { ...freshProfile.options, cities: [{ name: 'London', country: 'gb', boards: [], cv: { photo: 'no' as const, date_of_birth: false, max_pages: 2, date_format: 'DD/MM/YYYY' } }] } }
    setup({ ...answers, location: 'London' }, {}, noPhoto)
    expect(screen.queryByRole('button', { name: /photo/i })).toBeNull()
  })

  it('a refused picture is said under the photo and the wizard stays', async () => {
    const h = setup({ ...answers, photo: { kind: 'new', token: 't1', name: 'tiny.png' } })
    h.savePhoto.mockResolvedValueOnce({ ok: false, error: 'the picture is too small (50 x 50 px)' })
    await userEvent.click(screen.getByRole('button', { name: 'Save and start searching' }))
    expect(await within(part('You')).findByText(/too small/)).toBeInTheDocument()
    expect(h.onSaved).not.toHaveBeenCalled()
  })

  it('Remove drops a pick that was not saved', async () => {
    setup({ ...answers, photo: { kind: 'new', token: 't1', name: 'me.png' } })
    await userEvent.click(within(part('You')).getByRole('button', { name: 'Remove' }))
    expect(seen.photo).toEqual({ kind: 'keep' })
  })

  it('a photo already kept is shown, and Remove marks it for removal on Save', async () => {
    const kept = { ...existingProfile, photo: { exists: true, path: '/p/profile/photo.jpg' } }
    setup({ ...answers }, {}, kept)
    expect(within(part('You')).getByRole('img', { name: 'Your photo' })).toBeInTheDocument()
    await userEvent.click(within(part('You')).getByRole('button', { name: 'Remove' }))
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

  it('titles show their reasons, the best ones ticked, and take the user\'s own', async () => {
    setup()
    const titles = within(part('Titles'))
    expect(titles.getByRole('checkbox', { name: /Lead you led a team/ })).toBeChecked()
    expect(titles.getByRole('checkbox', { name: /Quant maths/ })).not.toBeChecked()
    await userEvent.type(titles.getByLabelText('Add your own title'), 'Actuary{Enter}')
    expect(titles.queryByRole('checkbox', { name: /Actuary/ })).toBeNull()
    await userEvent.click(titles.getByRole('button', { name: 'Remove Actuary' }))
    expect(titles.queryByText('Actuary')).toBeNull()
  })

  it('changing the titles proposes the terms again, debounced, and holds Save until then', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const h = setup()
    fireEvent.click(within(part('Titles')).getByRole('checkbox', { name: /Quant/ }))
    fireEvent.click(within(part('Titles')).getByRole('checkbox', { name: /Lead/ }))
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
    fireEvent.click(within(part('Titles')).getByRole('checkbox', { name: /Lead/ }))
    fireEvent.click(within(part('Titles')).getByRole('checkbox', { name: /Lead/ }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TERMS_DEBOUNCE_MS + 10)
    })
    expect(h.call).not.toHaveBeenCalledWith('keywords', expect.anything())
  })

  it('a failed proposal says the titles stand in', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    setup(answers, { keywords: () => { throw new Error('quota') } })
    fireEvent.click(within(part('Titles')).getByRole('checkbox', { name: /Quant/ }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TERMS_DEBOUNCE_MS + 10)
    })
    await waitFor(() => expect(seen.keywordsState).toBe('skipped'))
    expect(screen.getByText(/searched as they are: quota/)).toBeInTheDocument()
  })

  it('says what Claude could not do while reading, each where it belongs', () => {
    setup({ ...answers, warnings: { basics: 'usage limit', titles: 'overloaded', terms: 'quota' } })
    expect(within(part('You')).getByText('Claude could not read your details: usage limit')).toBeInTheDocument()
    expect(within(part('Titles')).getByText('Claude could not suggest titles: overloaded')).toBeInTheDocument()
    const terms = screen.getByText('Search', { selector: 'summary span' }).closest('details')!
    expect(terms.open).toBe(true)
    expect(within(terms).getByText('Claude could not propose search terms, so your titles are searched as they are: quota')).toBeInTheDocument()
  })

  it('every title unticked while new terms are on their way: Save asks for a title, and the late terms are dropped', async () => {
    let answer: (v: unknown) => void = () => undefined
    vi.useFakeTimers({ shouldAdvanceTime: true })
    setup(answers, { keywords: () => new Promise((r) => { answer = r }) })
    fireEvent.click(within(part('Titles')).getByRole('checkbox', { name: /Quant/ }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TERMS_DEBOUNCE_MS + 10)
    })
    expect(screen.getByText('Choosing search terms for your titles…')).toBeInTheDocument()
    fireEvent.click(within(part('Titles')).getByRole('checkbox', { name: /Lead/ }))
    fireEvent.click(within(part('Titles')).getByRole('checkbox', { name: /Quant/ }))
    expect(screen.getByText('Choose at least one title.')).toBeInTheDocument()
    await act(async () => answer({ keywords: ['late'], topic_terms: [] }))
    expect(seen.keywords).toEqual(['lead'])
  })

  it('search terms are folded by default', () => {
    setup()
    const terms = screen.getByText('Search', { selector: 'summary span' }).closest('details')!
    expect(terms.open).toBe(false)
    expect(within(terms).getByText('1 search terms, 1 title terms')).toBeInTheDocument()
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

  it('with no suggested titles, has no empty list before the box', () => {
    setup({ ...answers, titles: [], roleTargets: [] })
    expect(within(part('Titles')).queryByRole('group')).toBeNull()
    expect(within(part('Titles')).getByRole('textbox', { name: 'Add your own title' })).toBeInTheDocument()
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

  it('a refused Save stays here with each line under its section', async () => {
    setup(answers, { init_profile: () => { throw new Error('profile/config.json: name — too odd\nprofile/config.json: search_keywords — bad') } })
    await userEvent.click(screen.getByRole('button', { name: 'Save and start searching' }))
    expect(await within(part('You')).findByRole('alert')).toHaveTextContent('too odd')
    const terms = screen.getByText('Search', { selector: 'summary span' }).closest('details')!
    expect(terms.open).toBe(true)
    expect(within(terms).getByRole('alert')).toHaveTextContent('bad')
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
    const bank = part('Your story bank')
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
    await userEvent.click(within(part('Your story bank')).getByRole('checkbox', { name: 'Keep this story' }))
    expect(within(part('Your story bank')).queryByLabelText('Context')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Save and start searching' }))
    await waitFor(() => expect(h.onSaved).toHaveBeenCalled())
    expect(h.call.mock.calls.map((c) => c[0])).not.toContain('save_story')
  })

  it('without one, no story bank part', () => {
    setup()
    expect(screen.queryByRole('region', { name: 'Your story bank' })).toBeNull()
  })
})
