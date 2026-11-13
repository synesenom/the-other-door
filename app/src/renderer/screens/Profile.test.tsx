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
]

const show = (config: Record<string, unknown> = {}) => ({
  path: '/home/ada/profile',
  config: { name: 'Ada Lovelace', email: 'ada@example.com', location: 'Copenhagen', cv_template: '/home/ada/profile/cv.template.tex', role_targets: ['Data Analyst'], remote: 'hybrid', languages: ['English'], ...config },
  errors: [],
  cv: { path: '', exists: true, is_example: false, text: '', headline: null, sections: [] },
  options: { cities: [{ name: 'Copenhagen', country: 'Denmark', boards: ['jobindex'] }, { name: 'Aarhus', country: 'Denmark', boards: ['jobindex'] }], languages: ['English', 'Danish'], worldwide_boards: [], fields: FIELDS },
  enrich_sources: [],
})

async function open(handlers: Record<string, unknown> = {}, config: Record<string, unknown> = {}) {
  const h = mockDoor({ show_profile: show(config), ...handlers })
  const onSaved = vi.fn()
  const onDraft = vi.fn()
  render(<Profile onSaved={onSaved} onDraft={onDraft} />)
  await screen.findByRole('heading', { name: 'Profile', level: 1 })
  await screen.findByRole('region', { name: 'About you' })
  return { ...h, onSaved }
}

const saveButton = () => screen.getByRole('button', { name: 'Save' })

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
    const h = mockDoor({ show_profile: shown, list_companies: { companies: [] }, ...handlers })
    render(<Profile onSaved={() => {}} onDraft={() => {}} />)
    await screen.findByRole('region', { name: 'About you' })
    return h
  }

  it('is offered where the country\'s CVs may carry one, and saved at once, not with Save', async () => {
    const h = await openWith(profile('Copenhagen'))
    h.pickPhoto.mockResolvedValueOnce({ token: 't1', name: 'me.jpg' })
    h.call.mockClear()
    await userEvent.click(within(about()).getByRole('button', { name: 'Choose a photo…' }))
    await waitFor(() => expect(h.savePhoto).toHaveBeenCalledWith('t1'))
    expect(h.call).toHaveBeenCalledWith('show_profile', {})
    expect(saveButton()).toBeDisabled()
  })

  it('shows the photo kept, and Remove deletes it through remove_photo', async () => {
    const h = await openWith(profile('Copenhagen', { exists: true, path: '/home/ada/profile/photo.jpg' }), { remove_photo: { removed: true } })
    expect(within(about()).getByRole('img', { name: 'Your photo' })).toHaveAttribute('src', expect.stringContaining('door-file://profile/photo.jpg'))
    await userEvent.click(within(about()).getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(h.call).toHaveBeenCalledWith('remove_photo', {}))
  })

  it('says why a picture was refused, under the field', async () => {
    const h = await openWith(profile('Copenhagen'))
    h.pickPhoto.mockResolvedValueOnce({ token: 't1', name: 'tiny.png' })
    h.savePhoto.mockResolvedValueOnce({ ok: false, error: 'the picture is too small (50 x 50 px)' })
    await userEvent.click(within(about()).getByRole('button', { name: 'Choose a photo…' }))
    expect(await within(about()).findByRole('alert')).toHaveTextContent('too small')
    h.pickPhoto.mockResolvedValueOnce({ error: 'Choose a JPEG or PNG picture.' })
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
    const h = await openWith(profile('Copenhagen'))
    await userEvent.clear(screen.getByLabelText('Name'))
    await userEvent.type(screen.getByLabelText('Name'), 'Ada King')
    h.pickPhoto.mockResolvedValueOnce({ token: 't1', name: 'me.jpg' })
    await userEvent.click(within(about()).getByRole('button', { name: 'Choose a photo…' }))
    await waitFor(() => expect(h.savePhoto).toHaveBeenCalled())
    expect(screen.getByLabelText('Name')).toHaveValue('Ada King')
  })
})

describe('Profile, opened at a section', () => {
  it('scrolls to the section named', async () => {
    const scrolled: string[] = []
    Element.prototype.scrollIntoView = vi.fn(function (this: Element) {
      scrolled.push(this.id)
    })
    mockDoor({ show_profile: show() })
    render(<Profile onSaved={() => {}} onDraft={() => {}} start={{ section: 'skip' }} />)
    await waitFor(() => expect(scrolled).toEqual(['profile-skip']))
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
    expect(saveButton()).toBeDisabled()
  })

  it('saves only what changed, by name or in other, and reads the profile again', async () => {
    const { call, onSaved } = await open({ init_profile: { config_path: '/x' } })
    await userEvent.clear(screen.getByLabelText('Name'))
    await userEvent.type(screen.getByLabelText('Name'), 'Ada King')
    await userEvent.click(screen.getByRole('checkbox', { name: 'I need a visa or work permit' }))
    expect(screen.getByText('2 unsaved changes')).toBeInTheDocument()
    await userEvent.click(saveButton())
    expect(call).toHaveBeenCalledWith('init_profile', { name: 'Ada King', other: { needs_work_permit: true } })
    expect(await screen.findByText('Saved.')).toBeInTheDocument()
    expect(call.mock.calls.filter((c) => c[0] === 'show_profile')).toHaveLength(2)
    expect(onSaved).toHaveBeenCalled()
  })

  it('the preferences are a text area saved as written, with a line that it applies from the next run', async () => {
    const { call } = await open({ init_profile: {} })
    const box = screen.getByLabelText('What matters to you')
    expect(box.tagName).toBe('TEXTAREA')
    expect(box).toHaveValue('')
    await userEvent.type(box, 'medical; not banking')
    await userEvent.click(saveButton())
    expect(call).toHaveBeenCalledWith('init_profile', { other: { preferences: 'medical; not banking' } })
    expect(screen.getByRole('button', { name: 'About What matters to you' })).toBeInTheDocument()
  })

  it('the minimum score is one of three words, a hand-set value a fourth', async () => {
    const { call } = await open({ init_profile: {} })
    expect(screen.getByRole('radio', { name: 'Balanced' })).toBeChecked()
    await userEvent.click(screen.getByRole('radio', { name: 'Strong' }))
    await userEvent.click(saveButton())
    expect(call).toHaveBeenCalledWith('init_profile', { min_score: 0.75 })
    cleanup()
    await open({}, { min_score: 0.7 })
    expect(screen.getByRole('radio', { name: 'Your own (0.7)' })).toBeChecked()
  })

  it('an error is said under its field, and nothing is lost', async () => {
    await open({
      init_profile: () => {
        throw { message: 'profile/config.json: email — value is not a valid email address\nprofile/config.json: bogus — Extra inputs are not permitted' }
      },
    })
    await userEvent.clear(screen.getByLabelText('Email'))
    await userEvent.type(screen.getByLabelText('Email'), 'ada')
    await userEvent.click(saveButton())
    const field = screen.getByLabelText('Email').closest('.field') as HTMLElement
    expect(await within(field).findByText('value is not a valid email address')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('bogus')
    expect(screen.getByLabelText('Email')).toHaveValue('ada')
  })

  it('Undo changes puts the saved values back', async () => {
    await open()
    await userEvent.type(screen.getByLabelText('Name'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Undo changes' }))
    expect(screen.getByLabelText('Name')).toHaveValue('Ada Lovelace')
    expect(saveButton()).toBeDisabled()
  })

  it('exclude: companies and words as chips, sent as exclude_*', async () => {
    const { call } = await open({ init_profile: {} })
    await userEvent.type(screen.getByLabelText('Companies to skip'), 'Acme{Enter}')
    await userEvent.click(saveButton())
    expect(call).toHaveBeenCalledWith('init_profile', { exclude_companies: ['Acme'] })
  })

  it('the tuning keys and file paths are left to config.json: not shown, never sent', async () => {
    const { call } = await open({ init_profile: {} }, { scrape_workers: 4 })
    expect(screen.queryByText('/home/ada/profile/cv.template.tex')).toBeNull()
    expect(screen.queryByLabelText('Sites read at once')).toBeNull()
    await userEvent.type(screen.getByLabelText('Name'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(call).toHaveBeenCalledWith('init_profile', { name: 'Ada Lovelacex' })
  })

  it('a change of role targets has Claude propose the search terms again on Save', async () => {
    let config: Record<string, unknown> = { search_keywords: ['Data Analyst'] }
    const { call } = await open({
      show_profile: () => show(config),
      init_profile: (args: Record<string, unknown>) => {
        config = { ...config, ...args }
        return { config_path: '/x' }
      },
      keywords: () => {
        config = { ...config, search_keywords: ['Data Analyst', 'BI Analyst', 'Dataanalytiker'], topic_terms: ['analytiker'] }
        return { keywords: config['search_keywords'], topic_terms: config['topic_terms'], saved: true }
      },
    })
    await userEvent.type(screen.getByLabelText('Role targets'), 'BI Analyst{Enter}')
    await userEvent.click(saveButton())
    await waitFor(() => expect(call).toHaveBeenCalledWith('keywords', { role_targets: ['Data Analyst', 'BI Analyst'], languages: ['English'], save: true }))
    const names = call.mock.calls.map((c) => c[0])
    expect(names.indexOf('init_profile')).toBeLessThan(names.indexOf('keywords'))
    expect(await screen.findByText('Saved.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Search keywords')).toBeNull()
  })

  it('a save that leaves the role targets and languages alone asks Claude nothing', async () => {
    const { call } = await open({ init_profile: { config_path: '/x' } })
    await userEvent.type(screen.getByLabelText('Name'), 'x')
    await userEvent.click(saveButton())
    expect(await screen.findByText('Saved.')).toBeInTheDocument()
    expect(call.mock.calls.map((c) => c[0])).not.toContain('keywords')
  })

  it('the switch at the top shows the CV instead of the details', async () => {
    await open()
    expect(screen.getByRole('button', { name: 'Details' })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'CV' }))
    expect(await screen.findByLabelText('Your CV (Markdown)')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'About you' })).toBeNull()
  })

  it('a config that does not load says why, with the lines', async () => {
    mockDoor({ show_profile: { ...show(), config: null, errors: ['profile/config.json: remote — bad'] } })
    render(<Profile onSaved={() => {}} onDraft={() => {}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('remote — bad')
  })
})

describe('Profile, keeping what is shown true', () => {
  it('Undo after Other… puts the saved city back in the list', async () => {
    await open()
    await userEvent.selectOptions(screen.getByLabelText('City'), 'Other…')
    await userEvent.type(screen.getByLabelText('Your city'), 'Reykjavik')
    await userEvent.click(screen.getByRole('button', { name: 'Undo changes' }))
    expect(screen.queryByLabelText('Your city')).toBeNull()
    expect(screen.getByLabelText('City')).toHaveValue('Copenhagen')
  })

  it('the CV can be reached when the details cannot be read', async () => {
    let reads = 0
    mockDoor({
      show_profile: () => {
        if (reads++ === 0) throw { message: 'profile/ is not readable' }
        return show()
      },
    })
    render(<Profile onSaved={() => {}} onDraft={() => {}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('profile/ is not readable')
    await userEvent.click(within(screen.getByRole('group', { name: 'Part of the profile' })).getByRole('button', { name: 'CV' }))
    expect(await screen.findByLabelText('Your CV (Markdown)')).toBeInTheDocument()
  })

  it('unsaved CV text survives a look at the details', async () => {
    await open()
    await userEvent.click(screen.getByRole('button', { name: 'CV' }))
    await userEvent.type(await screen.findByLabelText('Your CV (Markdown)'), '# Ada, rewritten')
    await userEvent.click(screen.getByRole('button', { name: 'Details' }))
    await userEvent.click(screen.getByRole('button', { name: 'CV' }))
    expect(await screen.findByLabelText('Your CV (Markdown)')).toHaveValue('# Ada, rewritten')
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument()
  })

  it('has a Stories part; unsaved details survive a look at it', async () => {
    await open({ list_stories: { path: '/p/story_bank.md', exists: true, is_example: false, stories: [{ title: 'Cut build time', context: 'c', action: 'a', result: 'r', learning: 'x' }] } })
    const group = within(screen.getByRole('group', { name: 'Part of the profile' }))
    expect(group.getByRole('button', { name: 'Stories' })).toHaveAttribute('aria-pressed', 'false')
    await userEvent.clear(screen.getByLabelText('Name'))
    await userEvent.type(screen.getByLabelText('Name'), 'Ada B')
    await userEvent.click(group.getByRole('button', { name: 'Stories' }))
    expect(await screen.findByRole('listitem', { name: 'Cut build time' })).toBeInTheDocument()
    expect(group.getByRole('button', { name: 'Stories' })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(group.getByRole('button', { name: 'Details' }))
    expect(screen.getByLabelText('Name')).toHaveValue('Ada B')
  })

  it('the CV can be reached when config.json is not valid', async () => {
    mockDoor({ show_profile: { ...show(), config: null, errors: ['profile/config.json: remote — bad'] } })
    render(<Profile onSaved={() => {}} onDraft={() => {}} />)
    await screen.findByRole('alert')
    expect(within(screen.getByRole('group', { name: 'Part of the profile' })).getByRole('button', { name: 'CV' })).toBeInTheDocument()
  })
})
