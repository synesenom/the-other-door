// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../testing'
import { CvEditor } from './CvEditor'
import { Profile } from './Profile'

afterEach(cleanup)

const CV = '# Ada Lovelace\n\n## Experience\n\n- Analyst at Acme\n'

const profile = (cv: Partial<{ text: string | null; is_example: boolean; exists: boolean }> = {}, sources: string[] = []) => ({
  path: '/p',
  config: { role_targets: ['Data Analyst'], enrich_sources: sources },
  errors: [],
  cv: { path: '/p/cv.md', exists: true, is_example: false, text: CV, headline: null, sections: [], ...cv },
  options: { cities: [], languages: [], worldwide_boards: [] },
  enrich_sources: sources,
})

const NO_STORIES = { list_stories: { exists: false, stories: [] }, cv_style_sample: { png_base64: 'PNG', own_cv: true } } // the parts of Profile beside the CV

/** The CV as Profile shows it: Profile's one save bar saves it. */
async function open(handlers: Record<string, unknown> = {}, cv = {}, sources: string[] = []) {
  const h = mockDoor({ show_profile: profile(cv, sources), ...NO_STORIES, ...handlers })
  const onDraft = vi.fn()
  const onSaved = vi.fn()
  render(<Profile onDraft={onDraft} onSaved={onSaved} />)
  // loaded once its fields are; a CV with text opens on how it reads, and these tests edit it
  await screen.findByRole('group', { name: 'Sources' })
  const preview = screen.getByRole('switch', { name: 'Preview' })
  if (preview.getAttribute('aria-checked') === 'true') await userEvent.click(preview)
  return { ...h, onDraft, onSaved }
}

/** Profile as it opens: the Master CV formatted, not yet edited. */
async function show(cv = {}) {
  mockDoor({ show_profile: profile(cv), ...NO_STORIES })
  render(<Profile onDraft={vi.fn()} onSaved={vi.fn()} />)
  await screen.findByRole('heading', { name: 'Master CV' })
}

const editor = () => screen.getByLabelText('Your CV (Markdown)')

describe('CvEditor', () => {
  it('opens on the CV as it reads, Preview on; off shows its text, on again how it reads', async () => {
    await show()
    expect(await screen.findByRole('heading', { name: 'Experience' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Your CV (Markdown)')).toBeNull()
    await userEvent.click(screen.getByRole('switch', { name: 'Preview' }))
    expect(editor()).toHaveValue(CV)
    expect(screen.queryByRole('heading', { name: 'Experience' })).toBeNull()
    await userEvent.click(screen.getByRole('switch', { name: 'Preview' }))
    expect(screen.getByRole('heading', { name: 'Experience' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Your CV (Markdown)')).toBeNull()
  })

  it('an empty CV has nothing to read: it opens on its text, and stays there as it is typed into', async () => {
    await show({ text: '' })
    expect(await screen.findByLabelText('Your CV (Markdown)')).toHaveValue('')
    expect(screen.getByRole('switch', { name: 'Preview' })).not.toBeChecked()
    // typed into, it stays the text, and Preview shows how it reads
    await userEvent.type(editor(), '# Ada')
    expect(editor()).toHaveValue('# Ada')
    await userEvent.click(screen.getByRole('switch', { name: 'Preview' }))
    expect(screen.getByRole('heading', { name: 'Ada' })).toBeInTheDocument()
  })

  it('each gap is marked in the CV as it reads; a marker opens the text with that gap selected', async () => {
    const text = '# Ada\n\nBorn TODO in London.\n\n- Analyst at TODO\n'
    await show({ text })
    const marks = screen.getAllByRole('button', { name: 'to fill in' })
    expect(marks).toHaveLength(2)
    await userEvent.click(marks[1]!)
    const box = editor() as HTMLTextAreaElement
    expect(box).toHaveFocus()
    expect(text.slice(box.selectionStart, box.selectionEnd)).toBe('TODO')
    expect(box.selectionStart).toBe(text.lastIndexOf('TODO'))
  })

  it('saves itself when the editor is left: the first save keeps the backup, the later ones leave it', async () => {
    const { call } = await open({ save_cv: { cv_path: '/p/cv.md', backup: '/p/cv.md.bak' } })
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull() // the CV has no Save of its own, and the details' bar waits for a change
    await userEvent.type(editor(), '- SQL{Enter}')
    await userEvent.tab()
    await waitFor(() => expect(call).toHaveBeenCalledWith('save_cv', { markdown: `${CV}- SQL\n`, backup: true }))
    expect(await screen.findByRole('status')).toHaveTextContent('Saved')
    await userEvent.type(editor(), '- R{Enter}')
    await userEvent.tab()
    await waitFor(() => expect(call).toHaveBeenCalledWith('save_cv', { markdown: `${CV}- SQL\n- R\n`, backup: false }))
  })

  it('saves itself a moment after typing stops', async () => {
    const { call } = await open({ save_cv: { cv_path: '/p/cv.md', backup: null } })
    await userEvent.type(editor(), 'x')
    expect(call.mock.calls.some((c) => c[0] === 'save_cv')).toBe(false)
    await waitFor(() => expect(call).toHaveBeenCalledWith('save_cv', { markdown: `${CV}x`, backup: true }), { timeout: 3000 })
  })

  it('what was typed just before Profile is left is saved as it goes', async () => {
    const { call } = await open({ save_cv: { cv_path: '/p/cv.md', backup: null } })
    fireEvent.change(editor(), { target: { value: `${CV}x` } }) // no pause, no blur
    cleanup() // another destination: Profile unmounts
    await waitFor(() => expect(call).toHaveBeenCalledWith('save_cv', { markdown: `${CV}x`, backup: true }))
  })

  it('what was typed just before the window closes is saved, and the close waits for it', async () => {
    const { call, pushBeforeClose } = await open({ save_cv: { cv_path: '/p/cv.md', backup: null } })
    fireEvent.change(editor(), { target: { value: `${CV}x` } }) // no pause, no blur
    await pushBeforeClose()
    expect(call).toHaveBeenCalledWith('save_cv', { markdown: `${CV}x`, backup: true })
  })

  it('the first CV saved has the profile read again, so the sidebar\'s "no CV yet" goes', async () => {
    const { onSaved } = await open({ save_cv: { cv_path: '/p/cv.md', backup: null } }, { exists: false, text: null })
    await userEvent.type(editor(), '# Ada')
    await userEvent.tab()
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
  })

  it('an emptied CV is never written', async () => {
    const { call } = await open({ save_cv: {} })
    await userEvent.clear(editor())
    await userEvent.tab()
    await new Promise((r) => setTimeout(r, 1200))
    expect(call.mock.calls.some((c) => c[0] === 'save_cv')).toBe(false)
  })

  it('a cv.md that cannot be read as text is said, and saving keeps it as cv.md.bak', async () => {
    await open({}, { exists: true, text: null })
    expect(screen.getByRole('note')).toHaveTextContent('profile/cv.md could not be read as text')
    expect(screen.getByRole('note')).toHaveTextContent('cv.md.bak')
  })

  it('no CV yet: an empty editor, and a note whose link opens the draft', async () => {
    const { onDraft } = await open({}, { exists: false, text: null })
    expect(editor()).toHaveValue('')
    expect(screen.getByRole('note')).toHaveTextContent('You have no CV yet.')
    await userEvent.click(within(screen.getByRole('note')).getByRole('button', { name: 'Draft it from your CV file or pages' }))
    expect(onDraft).toHaveBeenCalled()
  })

  it('the example CV gets no note: no user has it', async () => {
    await open({}, { is_example: true })
    expect(screen.queryByRole('note')).toBeNull()
  })
})

describe('Add a page', () => {
  const proposals = {
    outcome: 'proposed',
    urls: ['https://ada.dev'],
    proposals: [
      { n: 1, section: 'Projects', text: 'Built a churn model in Python', source: 'https://ada.dev' },
      { n: 2, section: 'Skills', text: 'dbt', source: 'https://ada.dev' },
    ],
    unreachable: [],
  }
  const dialog = () => screen.getByRole('dialog', { name: 'Add a page' })
  const readPage = async (url = 'https://ada.dev') => {
    await userEvent.click(screen.getByRole('button', { name: 'Add a page' }))
    await userEvent.type(within(dialog()).getByLabelText('Which page?'), url)
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Read it' }))
  }
  // the CV as the server has it after "Add … to my Master CV" put the chosen line in
  const ADDED = `${CV}- Built a churn model in Python\n`
  const marked = () => [...document.querySelectorAll('.md-added')].map((m) => m.textContent)

  it('reads the one page asked for, remembers it, and adds only the ticked proposals, grouped by section', async () => {
    const answers: Record<string, unknown>[] = []
    let applied = false
    const { call } = await open({
      init_profile: {},
      show_profile: () => profile({ text: applied ? ADDED : CV }),
      enrich: (args: Record<string, unknown>) => {
        answers.push(args)
        if (!args['apply']) return proposals
        applied = true
        return { outcome: 'applied', added: [proposals.proposals[0]], cv_path: '/p/cv.md', backup: '/p/cv.md.bak' }
      },
    })
    await readPage()
    expect(answers[0]).toEqual({ urls: ['https://ada.dev'] })
    expect(call).toHaveBeenCalledWith('init_profile', { other: { enrich_sources: ['https://ada.dev'] } })
    expect(await within(dialog()).findByRole('group', { name: 'Projects' })).toBeInTheDocument()
    expect(within(dialog()).getByRole('group', { name: 'Skills' })).toBeInTheDocument()
    // one page: no "from" on every line
    expect(within(dialog()).queryByText(/from https/)).toBeNull()
    await userEvent.click(within(dialog()).getByRole('checkbox', { name: 'dbt' }))
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Add 1 to my Master CV' }))
    expect(answers[1]).toEqual({ apply: [1] })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    // what went in is marked in the CV, and nothing else is said
    expect(await screen.findByText('- Built a churn model in Python', { selector: '.md-added' })).toBeInTheDocument()
    expect(screen.queryByText(/Added 1/)).toBeNull()
    expect(screen.getByRole('list', { name: 'What your Master CV is read from' })).toHaveTextContent('ada.dev')
  })

  it('the added lines are marked in the CV as it reads and in its text, and go at the next edit', async () => {
    let applied = false
    await open({
      show_profile: () => profile({ text: applied ? ADDED : CV }),
      enrich: (args: Record<string, unknown>) => {
        if (!args['apply']) return proposals
        applied = true
        return { outcome: 'applied', added: [proposals.proposals[0]], cv_path: '/p/cv.md', backup: null }
      },
    })
    await readPage()
    await userEvent.click(await within(dialog()).findByRole('button', { name: 'Add 2 to my Master CV' }))
    await waitFor(() => expect(marked()).toEqual(['- Built a churn model in Python']))
    await userEvent.click(screen.getByRole('switch', { name: 'Preview' }))
    expect(marked()).toEqual(['Built a churn model in Python'])
    await userEvent.click(screen.getByRole('switch', { name: 'Preview' }))
    await userEvent.type(editor(), 'x')
    expect(marked()).toEqual([])
  })

  it('an address typed without https:// is read and remembered with it', async () => {
    const { call } = await open({ enrich: proposals })
    await readPage('github.com/ada')
    expect(call).toHaveBeenCalledWith('enrich', { urls: ['https://github.com/ada'] })
    expect(call).toHaveBeenCalledWith('init_profile', { other: { enrich_sources: ['https://github.com/ada'] } })
  })

  it('a page that cannot be read is said under the field and not remembered', async () => {
    const { call } = await open({ enrich: { outcome: 'nothing_new', urls: [], proposals: [], unreachable: ['https://gone.example'] } })
    await readPage('https://gone.example')
    expect(await within(dialog()).findByText('Could not read https://gone.example.')).toBeInTheDocument()
    expect(within(dialog()).getByLabelText('Which page?')).toHaveValue('https://gone.example')
    expect(call.mock.calls.some((c) => c[0] === 'init_profile')).toBe(false)
  })

  it('a read that fails says why, in the error box: it is no field\'s', async () => {
    await open({ enrich: () => { throw { message: 'claude is not signed in' } } })
    await readPage()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('claude is not signed in')
    expect(alert).toHaveClass('error')
  })

  it('nothing new is said so', async () => {
    await open({ enrich: { outcome: 'nothing_new', urls: ['https://ada.dev'], proposals: [], unreachable: [] } })
    await readPage()
    expect(await screen.findByText('Nothing on that page is missing from your Master CV.')).toBeInTheDocument()
  })

  it('Cancel closes it without reading', async () => {
    const { call } = await open()
    await userEvent.click(screen.getByRole('button', { name: 'Add a page' }))
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(call.mock.calls.some((c) => c[0] === 'enrich')).toBe(false)
  })

  it('writes what was typed before a page is read, since adding rewrites the CV', async () => {
    const { call } = await open({ save_cv: {} }, {}, ['https://ada.dev'])
    await userEvent.type(editor(), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Add a page' }))
    expect(call).toHaveBeenCalledWith('save_cv', { markdown: `${CV}x`, backup: true })
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })
})

describe('errors under their field', () => {
  it('a save that fails is said under the text, and tried again at the next pause', async () => {
    let fail = true
    const { call } = await open({ save_cv: () => { if (fail) throw { message: 'profile/ is not writable' }; return {} } })
    await userEvent.type(editor(), 'x')
    await userEvent.tab()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('profile/ is not writable')
    expect(alert).toHaveClass('field-error')
    expect(alert.closest('.profile-save')).toBeNull()
    fail = false
    await userEvent.type(editor(), 'y')
    await userEvent.tab()
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(call.mock.calls.filter((c) => c[0] === 'save_cv')).toHaveLength(2)
  })

  it('a page that cannot be forgotten is said under the Pages field', async () => {
    await open({ init_profile: () => { throw { message: 'config.json is not writable' } } }, {}, ['https://ada.dev'])
    await userEvent.click(screen.getByRole('button', { name: 'Forget https://ada.dev' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('config.json is not writable')
    expect(alert).toHaveClass('field-error')
    expect(within(screen.getByRole('group', { name: 'Sources' })).getByRole('alert')).toBe(alert)
    // the saved list still holds it: the chip comes back
    expect(screen.getByRole('button', { name: 'Forget https://ada.dev' })).toBeInTheDocument()
  })
})

describe('the pages read before', () => {
  const pages = () => screen.getByRole('list', { name: 'What your Master CV is read from' })

  it('are chips above the CV, each forgotten by its ×, saved at once', async () => {
    const { call } = await open({ init_profile: {} }, {}, ['https://ada.dev', 'https://github.com/ada'])
    expect(pages()).toHaveTextContent(/ada\.dev.*github\.com\/ada/)
    await userEvent.click(screen.getByRole('button', { name: 'Forget https://ada.dev' }))
    expect(call).toHaveBeenCalledWith('init_profile', { other: { enrich_sources: ['https://github.com/ada'] } })
    expect(pages()).not.toHaveTextContent('ada.dev,')
    expect(within(pages()).queryByTitle('https://ada.dev')).toBeNull()
  })

  it('none: no pages line and no Check again, only Add a page', async () => {
    await open()
    expect(screen.queryByRole('list', { name: 'What your Master CV is read from' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Check again' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Add a page' })).toBeEnabled()
  })

  it('Check again reads them all at once and names the page of each proposal', async () => {
    const two = {
      ...{ outcome: 'proposed', unreachable: [] },
      urls: ['https://ada.dev', 'https://github.com/ada'],
      proposals: [{ n: 1, section: 'Projects', text: 'A new repo', source: 'https://github.com/ada' }],
    }
    const { call } = await open({ enrich: two }, {}, ['https://ada.dev', 'https://github.com/ada'])
    await userEvent.click(screen.getByRole('button', { name: 'Check again' }))
    expect(call).toHaveBeenCalledWith('enrich', { urls: ['https://ada.dev', 'https://github.com/ada'] })
    const dialog = await screen.findByRole('dialog', { name: 'Check your pages again' })
    expect(await within(dialog).findByText(/from https:\/\/github\.com\/ada/)).toBeInTheDocument()
  })

  it('Check again with nothing new says so', async () => {
    await open({ enrich: { outcome: 'nothing_new', urls: ['https://ada.dev'], proposals: [], unreachable: [] } }, {}, ['https://ada.dev'])
    await userEvent.click(screen.getByRole('button', { name: 'Check again' }))
    expect(await screen.findByText('Nothing new on your pages.')).toBeInTheDocument()
  })
})

describe('CvEditor, the profile unreadable', () => {
  it('says why instead of an empty editor', async () => {
    mockDoor({ show_profile: () => { throw { message: 'profile/ is not readable' } } })
    render(<CvEditor onDraft={vi.fn()} onSaved={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('profile/ is not readable')
    expect(screen.queryByLabelText('Your CV (Markdown)')).toBeNull()
  })
})

describe('CvEditor, its part', () => {
  it('are Master CV (the file, the pages, the text), said to be what each application\'s CV is tailored from', async () => {
    mockDoor({ show_profile: profile() })
    render(<CvEditor onDraft={vi.fn()} />)
    await screen.findByRole('switch', { name: 'Preview' })
    const cv = within(screen.getByRole('region', { name: 'Master CV' }))
    expect(cv.getByText(/each application gets a CV of its own, picked from this one and tailored to the ad/)).toBeInTheDocument()
    expect(cv.getByRole('heading', { name: 'Experience' })).toBeInTheDocument()
    expect(cv.getByRole('button', { name: 'Add a page' })).toBeInTheDocument()
  })
})

describe('CvEditor, the CV file', () => {
  it('is named, by its name', async () => {
    const h = mockDoor({ show_profile: profile() })
    h.actions['cv-file'].mockResolvedValue('my cv.pdf')
    render(<CvEditor onDraft={vi.fn()} />)
    expect(await within(screen.getByRole('region', { name: 'Master CV' })).findByText('my cv.pdf')).toBeInTheDocument()
  })

  it('none known: no file among the sources, and Add a CV file…', async () => {
    await open()
    const sources = within(screen.getByRole('group', { name: 'Sources' }))
    expect(sources.queryByText(/\.pdf$/)).toBeNull()
    expect(sources.getByRole('button', { name: 'Add a CV file…' })).toBeInTheDocument()
  })

  it('a new CV file proposes what it adds, as a page does, and adds only what is ticked; nothing is drafted over the CV', async () => {
    const user = userEvent.setup()
    let applied = false
    const h = mockDoor({
      show_profile: () => profile({ text: applied ? `${CV}- Spoke at PyData\n` : CV }),
      enrich: (args: Record<string, unknown>) => {
        if (args['apply']) {
          applied = true
          return { outcome: 'applied', added: [{ n: 1, section: 'Talks', text: 'Spoke at PyData', source: 'new.pdf' }] }
        }
        return { outcome: 'proposed', files: args['files'], proposals: [{ n: 1, section: 'Talks', text: 'Spoke at PyData', source: 'new.pdf' }, { n: 2, section: 'Skills', text: 'dbt', source: 'new.pdf' }] }
      },
      ...NO_STORIES,
    })
    h.actions['cv-file'].mockResolvedValue('old.pdf')
    h.actions['pick-cv-files'].mockResolvedValue({ files: [{ token: 't1', name: 'new.pdf', size: 10 }], refused: [] })
    render(<Profile onDraft={vi.fn()} onSaved={vi.fn()} />)
    const replace = await screen.findByRole('button', { name: 'Replace CV file…' })
    h.actions['cv-file'].mockResolvedValue('new.pdf') // main remembers the file it reads
    await user.click(replace)
    const dialog = await screen.findByRole('dialog', { name: 'Replace your CV file' })
    expect(h.call).toHaveBeenCalledWith('enrich', {}, undefined, ['t1'])
    expect(within(dialog).getByText('The new file becomes your CV file.')).toBeInTheDocument()
    await user.click(await within(dialog).findByRole('checkbox', { name: /dbt/ }))
    await user.click(within(dialog).getByRole('button', { name: 'Add 1 to my Master CV' }))
    await waitFor(() => expect(h.call).toHaveBeenCalledWith('enrich', { apply: [1] }))
    expect(await screen.findByText('Spoke at PyData', { selector: '.md-added' })).toBeInTheDocument()
    expect(within(screen.getByRole('group', { name: 'Sources' })).getByText('new.pdf')).toBeInTheDocument()
    expect(h.call.mock.calls.some((c) => c[0] === 'draft_cv')).toBe(false)
  })

  it('with no Master CV yet, a CV file is drafted into it whole', async () => {
    const user = userEvent.setup()
    const h = mockDoor({ show_profile: profile({ text: '' }), draft_cv: { markdown: '# Ada\n\n## New\n', sources: [], provenance: [], todos: [] }, save_cv: { cv_path: '/p/cv.md', backup: null }, ...NO_STORIES })
    h.actions['pick-cv-files'].mockResolvedValue({ files: [{ token: 't1', name: 'new.pdf', size: 10 }], refused: [] })
    render(<Profile onDraft={vi.fn()} onSaved={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: 'Add a CV file…' }))
    expect(await screen.findByRole('heading', { name: 'New' })).toBeInTheDocument()
    expect(h.call).toHaveBeenCalledWith('draft_cv', { sources: [] }, undefined, ['t1'])
    await waitFor(() => expect(h.call).toHaveBeenCalledWith('save_cv', { markdown: '# Ada\n\n## New\n', backup: true }), { timeout: 3000 })
    expect(h.call.mock.calls.some((c) => c[0] === 'enrich')).toBe(false)
  })

  it('a file that cannot be read is said in the dialog, the CV untouched and the CV file kept', async () => {
    const user = userEvent.setup()
    const h = mockDoor({ show_profile: profile(), enrich: () => { throw { message: 'Claude did not answer. Try again.' } } })
    h.actions['cv-file'].mockResolvedValue('old.pdf')
    h.actions['pick-cv-files'].mockResolvedValue({ files: [{ token: 't1', name: 'new.pdf', size: 10 }], refused: [] })
    render(<CvEditor onDraft={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: 'Replace CV file…' }))
    const dialog = await screen.findByRole('dialog', { name: 'Replace your CV file' })
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Claude did not answer')
    expect(screen.getByRole('heading', { name: 'Experience' })).toBeInTheDocument()
    expect(h.call.mock.calls.some((c) => c[0] === 'draft_cv')).toBe(false)
  })

  it('a refused file is said by its reason', async () => {
    const user = userEvent.setup()
    const h = mockDoor({ show_profile: profile() })
    h.actions['pick-cv-files'].mockResolvedValue({ files: [], refused: [{ name: 'cv.exe', reason: 'not a CV file' }] })
    render(<CvEditor onDraft={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: 'Add a CV file…' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('cv.exe: not a CV file')
    expect(h.call.mock.calls.some((c) => c[0] === 'draft_cv')).toBe(false)
  })
})
