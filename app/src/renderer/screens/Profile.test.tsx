// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../testing'
import { Profile } from './Profile'
import type { FieldSpec } from './profile-form/form'

afterEach(cleanup)

const FIELDS: FieldSpec[] = [
  { key: 'name', type: 'string', required: true, nullable: false },
  { key: 'email', type: 'string', required: true, nullable: false },
  { key: 'location', type: 'string', required: true, nullable: false },
  { key: 'cv_template', type: 'path', required: true, nullable: false },
  { key: 'scrape_workers', type: 'integer', required: false, nullable: true, default: null, min: 1 },
  { key: 'role_targets', type: 'list', required: true, nullable: false },
  { key: 'search_keywords', type: 'list', required: false, nullable: false, default: [] },
  { key: 'topic_terms', type: 'list', required: false, nullable: false, default: [] },
  { key: 'remote', type: 'choice', required: true, nullable: false, choices: ['yes', 'no', 'hybrid'] },
  { key: 'linkedin_discovery', type: 'boolean', required: false, nullable: false, default: true },
  { key: 'needs_work_permit', type: 'boolean', required: false, nullable: false, default: false },
  { key: 'exclude', type: 'exclude', required: false, nullable: false, default: { companies: [], keywords: [] } },
  { key: 'min_score', type: 'number', required: false, nullable: false, default: 0.65 },
  { key: 'languages', type: 'list', required: false, nullable: false, default: [] },
  { key: 'claude_config_dir', type: 'string', required: false, nullable: true, default: null },
  { key: 'preferences', type: 'string', required: false, nullable: false, default: '' },
  { key: 'cv_accent', type: 'choice', required: false, nullable: false, default: 'blue', choices: ['none', 'blue', 'navy'] },
  { key: 'cv_fonts', type: 'choice', required: false, nullable: false, default: 'door', choices: ['door', 'plain'] },
]

const show = (config: Record<string, unknown> = {}) => ({
  path: '/home/ada/profile',
  config: { name: 'Ada Lovelace', email: 'ada@example.com', location: 'Copenhagen', cv_template: '/home/ada/profile/cv.template.html', role_targets: ['Data Analyst'], remote: 'hybrid', languages: ['English'], ...config },
  errors: [],
  cv: { path: '', exists: true, is_example: false, text: '', headline: null, sections: [] },
  options: { cities: [{ name: 'Copenhagen', country: 'Denmark', boards: ['jobindex'] }, { name: 'Aarhus', country: 'Denmark', boards: ['jobindex'] }], languages: ['English', 'Danish'], worldwide_boards: [], fields: FIELDS, cv_styles: {
    accents: { none: 'black', blue: 'navy', navy: 'blue' },
    fonts: { door: { heading: 'serif', text: 'sans-serif', weight: 400 }, plain: { heading: 'sans-serif', text: 'sans-serif', weight: 600 } },
  } },
  enrich_sources: [],
})

const NO_STORIES = { list_stories: { exists: false, stories: [] }, cv_style_sample: { png_base64: 'PNG', own_cv: true } }

async function open(handlers: Record<string, unknown> = {}, config: Record<string, unknown> = {}) {
  const h = mockDoor({ show_profile: show(config), ...NO_STORIES, ...handlers })
  const onSaved = vi.fn()
  const onDraft = vi.fn()
  render(<Profile onSaved={onSaved} onDraft={onDraft} />)
  await screen.findByRole('heading', { name: 'Profile', level: 1 })
  await screen.findByRole('region', { name: 'About you' })
  return { ...h, onSaved }
}

describe('Profile, the CV photo', () => {
  const fields: FieldSpec[] = [...FIELDS, { key: 'photo', type: 'path', required: false, nullable: true, default: null }]
  const cv = (photo: string) => ({ photo, date_of_birth: false, max_pages: 2, date_format: 'DD.MM.YYYY' })
  const options = {
    cities: [
      { name: 'Copenhagen', country: 'Denmark', boards: ['jobindex'], cv: cv('optional') },
      { name: 'London', country: 'United Kingdom', boards: [], cv: cv('no') },
    ],
    languages: ['English'], worldwide_boards: [], fields,
  }
  const profile = (location: string, photo?: { exists: boolean; path?: string }) => ({ ...show({ location }), options, photo: photo ?? { exists: false } })
  const about = () => screen.getByRole('region', { name: 'About you' })
  const openWith = async (shown: unknown, handlers: Record<string, unknown> = {}) => {
    const h = mockDoor({ show_profile: shown, ...handlers })
    render(<Profile onSaved={() => {}} onDraft={() => {}} />)
    await screen.findByRole('region', { name: 'About you' })
    return h
  }

  it('is offered where the country\'s CVs may carry one, and saved at once, not with Save', async () => {
    const h = await openWith(profile('Copenhagen'), { save_photo: { photo_path: '/p/photo.jpg' } })
    h.actions['pick-photo'].mockResolvedValueOnce({ token: 't1', name: 'me.jpg' })
    h.call.mockClear()
    await userEvent.click(within(about()).getByRole('button', { name: 'Choose a photo…' }))
    await waitFor(() => expect(h.call).toHaveBeenCalledWith('save_photo', {}, undefined, ['t1']))
    expect(h.call).toHaveBeenCalledWith('show_profile', {})
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
  })

  it('shows the photo kept, and Remove deletes it through remove_photo', async () => {
    const h = await openWith(profile('Copenhagen', { exists: true, path: '/home/ada/profile/photo.jpg' }), { remove_photo: { removed: true } })
    expect(within(about()).getByRole('img', { name: 'Your photo' })).toHaveAttribute('src', expect.stringContaining('door-file://profile/photo.jpg'))
    await userEvent.click(within(about()).getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(h.call).toHaveBeenCalledWith('remove_photo', {}))
  })

  it('says why a picture was refused, under the field', async () => {
    const h = await openWith(profile('Copenhagen'), {
      save_photo: () => {
      throw new Error('the picture is too small (50 x 50 px)')
    },
    })
    h.actions['pick-photo'].mockResolvedValueOnce({ token: 't1', name: 'tiny.png' })
    await userEvent.click(within(about()).getByRole('button', { name: 'Choose a photo…' }))
    expect(await within(about()).findByRole('alert')).toHaveTextContent('too small')
    h.actions['pick-photo'].mockResolvedValueOnce({ error: 'Choose a JPEG or PNG picture.' })
    await userEvent.click(within(about()).getByRole('button', { name: 'Choose a photo…' }))
    expect(await within(about()).findByRole('alert')).toHaveTextContent('JPEG or PNG')
  })

  it('is not offered where the country\'s CVs carry none, unless there is one to remove', async () => {
    await openWith(profile('London'))
    expect(screen.queryByRole('button', { name: /photo/i })).toBeNull()
    cleanup()
    await openWith(profile('London', { exists: true, path: '/p/photo.jpg' }))
    expect(within(about()).getByRole('button', { name: 'Remove' })).toBeInTheDocument()
  })

  it('keeps what is typed and unsaved when the photo changes', async () => {
    const h = await openWith(profile('Copenhagen'), { save_photo: { photo_path: '/p/photo.jpg' } })
    await userEvent.clear(screen.getByLabelText('Name'))
    await userEvent.type(screen.getByLabelText('Name'), 'Ada King')
    h.actions['pick-photo'].mockResolvedValueOnce({ token: 't1', name: 'me.jpg' })
    await userEvent.click(within(about()).getByRole('button', { name: 'Choose a photo…' }))
    await waitFor(() => expect(h.call).toHaveBeenCalledWith('save_photo', {}, undefined, ['t1']))
    expect(screen.getByLabelText('Name')).toHaveValue('Ada King')
  })
})

describe('Profile, opened at a section', () => {
  it('scrolls to the section named', async () => {
    const scrolled: string[] = []
    Element.prototype.scrollIntoView = vi.fn(function (this: Element) {
      scrolled.push(this.id)
    })
    mockDoor({ show_profile: show(), ...NO_STORIES })
    render(<Profile onSaved={() => {}} onDraft={() => {}} start={{ section: 'skip' }} />)
    await waitFor(() => expect(scrolled).toEqual(['profile-skip']))
  })

  it('the CV and the Stories are sections of the same page, scrolled to like the rest', async () => {
    const scrolled: string[] = []
    Element.prototype.scrollIntoView = vi.fn(function (this: Element) {
      scrolled.push(this.id)
    })
    mockDoor({ show_profile: show(), ...NO_STORIES })
    render(<Profile onSaved={() => {}} onDraft={() => {}} start={{ section: 'cv' }} />)
    await waitFor(() => expect(scrolled).toEqual(['profile-cv']))
  })
})

describe('Profile', () => {
  it('shows the sections with what is saved, the advanced keys folded away', async () => {
    await open()
    expect(screen.getByLabelText('Name')).toHaveValue('Ada Lovelace')
    expect(screen.getByLabelText('City')).toHaveValue('Copenhagen')
    expect(screen.getByRole('radio', { name: 'Hybrid' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'English' })).toBeChecked()
    expect(screen.getByRole('list', { name: 'Role targets, chosen' })).toHaveTextContent('Data Analyst')
    // how the app works is in Settings: the discovery switches and the Claude folder are not here
    expect(screen.queryByRole('checkbox', { name: 'LinkedIn' })).toBeNull()
    expect(screen.queryByLabelText('Claude config folder')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
  })

  it('saves a typed key alone, a second after typing stops, and a choice at once; no Save, no Undo', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
      const { call, onSaved } = await open({ init_profile: { config_path: '/x' } })
      await screen.findByRole('group', { name: 'Sources' })
      await user.clear(screen.getByLabelText('Name'))
      await user.type(screen.getByLabelText('Name'), 'Ada King')
      expect(call.mock.calls.filter((c) => c[0] === 'init_profile')).toHaveLength(0)
      await vi.advanceTimersByTimeAsync(1000)
      expect(call.mock.calls.filter((c) => c[0] === 'init_profile')).toEqual([['init_profile', { name: 'Ada King' }]])
      await user.click(screen.getByRole('checkbox', { name: 'I need a visa or work permit' }))
      await waitFor(() => expect(call).toHaveBeenCalledWith('init_profile', { other: { needs_work_permit: true } }))
      expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
      expect(screen.queryByRole('button', { name: 'Undo changes' })).toBeNull()
      expect(screen.queryByText(/unsaved/)).toBeNull()
      expect(call.mock.calls.some((c) => c[0] === 'save_cv')).toBe(false)
      expect(onSaved).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('leaving a field saves it at once', async () => {
    const { call } = await open({ init_profile: {} })
    const box = screen.getByLabelText('What matters to you')
    expect(box.tagName).toBe('TEXTAREA')
    await userEvent.type(box, 'medical; not banking')
    await userEvent.tab()
    await waitFor(() => expect(call).toHaveBeenCalledWith('init_profile', { other: { preferences: 'medical; not banking' } }))
    expect(screen.getByRole('button', { name: 'About What matters to you' })).toBeInTheDocument()
  })

  it('the minimum score is one of three words, a hand-set value a fourth', async () => {
    const { call } = await open({ init_profile: {} })
    expect(screen.getByRole('radio', { name: 'Balanced' })).toBeChecked()
    await userEvent.click(screen.getByRole('radio', { name: 'Strong' }))
    await waitFor(() => expect(call).toHaveBeenCalledWith('init_profile', { min_score: 0.75 }))
    cleanup()
    await open({}, { min_score: 0.7 })
    expect(screen.getByRole('radio', { name: 'Your own (0.70)' })).toBeChecked()
  })

  it('an error is said under its field, the value stays, and a later valid edit is sent again', async () => {
    let refuse = true
    const { call } = await open({
      init_profile: () => {
        if (refuse) throw { message: 'profile/config.json: email — value is not a valid email address\nprofile/config.json: bogus — Extra inputs are not permitted' }
        return {}
      },
    })
    await userEvent.clear(screen.getByLabelText('Email'))
    await userEvent.type(screen.getByLabelText('Email'), 'ada')
    await userEvent.tab()
    const field = screen.getByLabelText('Email').closest('.field') as HTMLElement
    expect(await within(field).findByText('value is not a valid email address')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('bogus')
    expect(screen.getByLabelText('Email')).toHaveValue('ada')
    // the same refused value is not sent again by the next blur
    await userEvent.click(screen.getByLabelText('Name'))
    await userEvent.tab()
    expect(call.mock.calls.filter((c) => c[0] === 'init_profile')).toHaveLength(1)
    refuse = false
    await userEvent.type(screen.getByLabelText('Email'), '@example.net')
    await userEvent.tab()
    await waitFor(() => expect(call).toHaveBeenLastCalledWith('init_profile', { email: 'ada@example.net' }))
    await waitFor(() => expect(within(field).queryByText('value is not a valid email address')).toBeNull())
  })

  it('exclude: companies and words as chips, sent as exclude_*', async () => {
    const { call } = await open({ init_profile: {} })
    await userEvent.type(screen.getByLabelText('Companies to skip'), 'Acme{Enter}')
    await waitFor(() => expect(call).toHaveBeenCalledWith('init_profile', { exclude_companies: ['Acme'] }))
  })

  it('the tuning keys and file paths are left to config.json: not shown, never sent', async () => {
    const { call } = await open({ init_profile: {} }, { scrape_workers: 4 })
    expect(screen.queryByText('/home/ada/profile/cv.template.html')).toBeNull()
    expect(screen.queryByLabelText('Sites read at once')).toBeNull()
    await userEvent.type(screen.getByLabelText('Name'), 'x')
    await userEvent.tab()
    await waitFor(() => expect(call).toHaveBeenCalledWith('init_profile', { name: 'Ada Lovelacex' }))
  })

  it('what is waiting is written when the window closes, and when Profile is left', async () => {
    const { call, pushBeforeClose } = await open({ init_profile: {} })
    await userEvent.type(screen.getByLabelText('Name'), 'x')
    await pushBeforeClose()
    expect(call).toHaveBeenCalledWith('init_profile', { name: 'Ada Lovelacex' })
    cleanup()
    const second = await open({ init_profile: {} })
    await userEvent.type(screen.getByLabelText('Name'), 'y')
    cleanup()
    await waitFor(() => expect(second.call).toHaveBeenCalledWith('init_profile', { name: 'Ada Lovelacey' }))
  })

  it('an autosave does not rewrite what is shown or read the profile again', async () => {
    const { call } = await open({ init_profile: {} })
    const reads = () => call.mock.calls.filter((c) => c[0] === 'show_profile').length
    await screen.findByRole('group', { name: 'Sources' })
    const before = reads()
    const name = screen.getByLabelText('Name')
    await userEvent.type(name, 'x')
    await userEvent.tab()
    await waitFor(() => expect(call).toHaveBeenCalledWith('init_profile', { name: 'Ada Lovelacex' }))
    expect(name).toHaveValue('Ada Lovelacex')
    expect(reads()).toBe(before)
  })

  describe('on leaving', () => {
    const openLeave = async (handlers: Record<string, unknown> = {}) => {
      const h = mockDoor({ show_profile: show(), ...NO_STORIES, init_profile: {}, ...handlers })
      const onLeave = vi.fn()
      render(<Profile onSaved={() => {}} onDraft={() => {}} onLeave={onLeave} />)
      await screen.findByRole('region', { name: 'About you' })
      return { ...h, onLeave }
    }

    it('says the role targets changed', async () => {
      const { call, onLeave } = await openLeave()
      await userEvent.type(screen.getByLabelText('Role targets'), 'BI Analyst{Enter}')
      cleanup()
      await waitFor(() => expect(onLeave).toHaveBeenCalledWith(true))
      expect(onLeave).toHaveBeenCalledTimes(1)
      expect(call).toHaveBeenCalledWith('init_profile', { role_targets: ['Data Analyst', 'BI Analyst'] })
      expect(call.mock.calls.some((c) => c[0] === 'keywords')).toBe(false) // the app proposes, not Profile
    })

    it('says the ad languages changed', async () => {
      const { onLeave } = await openLeave()
      await userEvent.click(screen.getByRole('checkbox', { name: 'Danish' }))
      cleanup()
      await waitFor(() => expect(onLeave).toHaveBeenCalledWith(true))
    })

    it('a name alone changes no search terms', async () => {
      const { onLeave } = await openLeave()
      await userEvent.type(screen.getByLabelText('Name'), 'x')
      cleanup()
      await waitFor(() => expect(onLeave).toHaveBeenCalledWith(false))
    })

    it('a role target added and taken away again changes nothing', async () => {
      const { onLeave } = await openLeave()
      await userEvent.type(screen.getByLabelText('Role targets'), 'BI Analyst{Enter}')
      await userEvent.click(screen.getByRole('button', { name: 'Remove BI Analyst' }))
      cleanup()
      await waitFor(() => expect(onLeave).toHaveBeenCalledWith(false))
    })

    it('nothing written: nothing said', async () => {
      const { onLeave } = await openLeave()
      cleanup()
      await new Promise((r) => setTimeout(r, 20))
      expect(onLeave).not.toHaveBeenCalled()
    })
  })

  it('is one page: the details, then the CV and the Stories, each listed beside it', async () => {
    await open()
    await screen.findByRole('group', { name: 'Sources' })
    const names = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)
    expect(names.slice(-3)).toEqual(['Master CV', 'CV style', 'Stories'])
    expect(names[0]).toBe('About you')
    expect(within(screen.getByRole('navigation', { name: 'Sections' })).getAllByRole('link').slice(-3).map((l) => l.textContent)).toEqual(['Master CV', 'CV style', 'Stories'])
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
  })

  it('the CV style is a section of the page, and its two keys are not in the form above it', async () => {
    await open()
    expect(await screen.findByRole('region', { name: 'CV style' })).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'CV colour' })).toBeNull()
    expect(screen.queryByRole('group', { name: 'CV fonts' })).toBeNull()
  })

  it('lists CV style beside the page only when the part is there', async () => {
    await open()
    const links = () => within(screen.getByRole('navigation', { name: 'Sections' })).getAllByRole('link').map((l) => l.textContent)
    expect(links()).toContain('CV style')
    cleanup()
    mockDoor({ show_profile: { ...show(), config: null, errors: ['profile/config.json: remote — bad'] }, ...NO_STORIES })
    render(<Profile onSaved={() => {}} onDraft={() => {}} />)
    await screen.findByRole('heading', { name: 'Master CV' })
    expect(links()).toEqual(['Master CV', 'Stories'])
    expect(screen.queryByRole('region', { name: 'CV style' })).toBeNull()
  })

  it('a config that does not load says why, with the lines', async () => {
    mockDoor({ show_profile: { ...show(), config: null, errors: ['profile/config.json: remote — bad'] }, ...NO_STORIES })
    render(<Profile onSaved={() => {}} onDraft={() => {}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('remote — bad')
  })
})

describe('Profile, keeping what is shown true', () => {
  it('the CV and the Stories are there when config.json is not valid', async () => {
    mockDoor({ show_profile: { ...show(), config: null, errors: ['profile/config.json: remote — bad'] }, ...NO_STORIES })
    render(<Profile onSaved={() => {}} onDraft={() => {}} />)
    expect(await screen.findByRole('heading', { name: 'Master CV' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('remote — bad')
    expect(screen.getByRole('region', { name: 'Stories' })).toBeInTheDocument()
  })

  it('a profile that cannot be read is said, and the Stories are still there', async () => {
    mockDoor({ show_profile: () => { throw { message: 'profile/ is not readable' } }, ...NO_STORIES })
    render(<Profile onSaved={() => {}} onDraft={() => {}} />)
    await waitFor(() => expect(screen.getAllByRole('alert').length).toBeGreaterThan(0))
    expect(screen.getAllByRole('alert')[0]).toHaveTextContent('profile/ is not readable')
    expect(screen.getByRole('region', { name: 'Stories' })).toBeInTheDocument()
  })

  it('the CV saves itself too, and nothing says anything is unsaved', async () => {
    const { call } = await open({ save_cv: {} })
    await userEvent.type(await screen.findByLabelText('Your CV (Markdown)'), '# Ada B')
    await userEvent.tab()
    await waitFor(() => expect(call).toHaveBeenCalledWith('save_cv', { markdown: '# Ada B', backup: true }))
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
    expect(screen.queryByText(/unsaved change/)).toBeNull()
  })


})
