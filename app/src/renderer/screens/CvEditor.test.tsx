// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../testing'
import { CvEditor } from './CvEditor'

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

async function open(handlers: Record<string, unknown> = {}, cv = {}, sources: string[] = []) {
  const h = mockDoor({ show_profile: profile(cv, sources), ...handlers })
  const onDraft = vi.fn()
  const onSaved = vi.fn()
  render(<CvEditor onDraft={onDraft} onSaved={onSaved} />)
  await screen.findByLabelText('Your CV (Markdown)')
  return { ...h, onDraft, onSaved }
}

const editor = () => screen.getByLabelText('Your CV (Markdown)')

describe('CvEditor', () => {
  it('shows the CV in the editor, and a preview on request', async () => {
    await open()
    expect(editor()).toHaveValue(CV)
    await userEvent.click(screen.getByRole('switch', { name: 'Preview' }))
    expect(screen.getByRole('heading', { name: 'Experience' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Your CV (Markdown)')).toBeNull()
  })

  it('the preview marks each gap; a marker opens the editor with that gap selected', async () => {
    const text = '# Ada\n\nBorn TODO in London.\n\n- Analyst at TODO\n'
    await open({}, { text })
    await userEvent.click(screen.getByRole('switch', { name: 'Preview' }))
    const marks = screen.getAllByRole('button', { name: 'to fill in' })
    expect(marks).toHaveLength(2)
    await userEvent.click(marks[1]!)
    const box = editor() as HTMLTextAreaElement
    expect(box).toHaveFocus()
    expect(text.slice(box.selectionStart, box.selectionEnd)).toBe('TODO')
    expect(box.selectionStart).toBe(text.lastIndexOf('TODO'))
    expect(screen.getByRole('switch', { name: 'Preview' })).not.toBeChecked()
  })

  it('saves through save_cv, says the old one is kept, and Save waits for a change', async () => {
    const { call } = await open({ save_cv: { cv_path: '/p/cv.md', backup: '/p/cv.md.bak' } })
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    await userEvent.type(editor(), '- SQL{Enter}')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(call).toHaveBeenCalledWith('save_cv', { markdown: `${CV}- SQL\n` })
    expect(await screen.findByText('Saved. The previous version is kept as cv.md.bak.')).toBeInTheDocument()
  })

  it('the first CV is saved with no word of a backup, and the profile is read again', async () => {
    const { onSaved } = await open({ save_cv: { cv_path: '/p/cv.md', backup: null } }, { exists: false, text: null })
    await userEvent.type(editor(), '# Ada')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('Saved.')).toBeInTheDocument()
    expect(screen.queryByText(/cv\.md\.bak/)).toBeNull()
    expect(onSaved).toHaveBeenCalled() // the sidebar's "no CV yet" goes
  })

  it('a cv.md that cannot be read as text is said, and saving keeps it as cv.md.bak', async () => {
    await open({}, { exists: true, text: null })
    expect(screen.getByRole('note')).toHaveTextContent('profile/cv.md could not be read as text')
    expect(screen.getByRole('note')).toHaveTextContent('cv.md.bak')
  })

  it('Undo changes puts the saved CV back', async () => {
    await open()
    await userEvent.type(editor(), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Undo changes' }))
    expect(editor()).toHaveValue(CV)
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
  // the CV as the server has it after "Add … to my CV" put the chosen line in
  const ADDED = `${CV}- Built a churn model in Python\n`
  const marked = () => [...document.querySelectorAll('.md-added')].map((m) => m.textContent)

  it('reads the one page asked for, remembers it, and adds only the ticked proposals, grouped by section', async () => {
    const answers: Record<string, unknown>[] = []
    let applied = false
    const { call } = await open({
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
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Add 1 to my CV' }))
    expect(answers[1]).toEqual({ apply: [1] })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    // what went in is marked in the CV, and nothing else is said
    expect(await screen.findByText('- Built a churn model in Python', { selector: '.md-added' })).toBeInTheDocument()
    expect(screen.queryByText(/Added 1/)).toBeNull()
    expect(screen.getByRole('list', { name: 'Pages your CV is read from' })).toHaveTextContent('ada.dev')
  })

  it('the added lines stay marked in the preview, and go at the next edit', async () => {
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
    await userEvent.click(await within(dialog()).findByRole('button', { name: 'Add 2 to my CV' }))
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
    expect(await screen.findByText('Nothing on that page is missing from your CV.')).toBeInTheDocument()
  })

  it('Cancel closes it without reading', async () => {
    const { call } = await open()
    await userEvent.click(screen.getByRole('button', { name: 'Add a page' }))
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(call.mock.calls.some((c) => c[0] === 'enrich')).toBe(false)
  })

  it('waits for unsaved edits to be saved or undone, since adding rewrites the CV', async () => {
    await open({}, {}, ['https://ada.dev'])
    await userEvent.type(editor(), 'x')
    expect(screen.getByRole('button', { name: 'Add a page' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Check again' })).toBeDisabled()
    expect(screen.getByText('Save or undo your changes before adding from a page.')).toBeInTheDocument()
  })
})

describe("errors that are no field's", () => {
  it('a Save that fails is said in the error box', async () => {
    await open({ save_cv: () => { throw { message: 'profile/ is not writable' } } })
    await userEvent.type(editor(), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('profile/ is not writable')
    expect(alert).toHaveClass('error')
    expect(alert).not.toHaveClass('field-error')
    // in the sticky Save bar, on its own line: seen from wherever Save was pressed
    expect(alert.closest('.profile-save')).not.toBeNull()
  })

  it('a page that cannot be forgotten is said in the error box', async () => {
    await open({ init_profile: () => { throw { message: 'config.json is not writable' } } }, {}, ['https://ada.dev'])
    await userEvent.click(screen.getByRole('button', { name: 'Forget https://ada.dev' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('config.json is not writable')
    expect(alert).toHaveClass('error')
    expect(alert).not.toHaveClass('field-error')
  })
})

describe('the pages read before', () => {
  const pages = () => screen.getByRole('list', { name: 'Pages your CV is read from' })

  it('are chips above the CV, each forgotten by its ×, saved at once', async () => {
    const { call } = await open({}, {}, ['https://ada.dev', 'https://github.com/ada'])
    expect(pages()).toHaveTextContent(/ada\.dev.*github\.com\/ada/)
    await userEvent.click(screen.getByRole('button', { name: 'Forget https://ada.dev' }))
    expect(call).toHaveBeenCalledWith('init_profile', { other: { enrich_sources: ['https://github.com/ada'] } })
    expect(pages()).not.toHaveTextContent('ada.dev,')
    expect(within(pages()).queryByTitle('https://ada.dev')).toBeNull()
  })

  it('none: no pages line and no Check again, only Add a page', async () => {
    await open()
    expect(screen.queryByRole('list', { name: 'Pages your CV is read from' })).toBeNull()
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

describe('CvEditor, the Style', () => {
  const styled = { show_style: { styles: { default: { cv: ['/h/cv_page_1.png'], letter: ['/h/letter_page_1.png'], version: 'v1', two_column: false } }, in_use: 'default', candidate: false } }

  it('is above the CV, and its previews are read again after a save', async () => {
    const h = mockDoor({ show_profile: profile(), save_cv: { cv_path: '/p/cv.md', backup: null }, ...styled })
    render(<CvEditor onDraft={vi.fn()} onSaved={vi.fn()} style={{ state: 'none', canBuild: true, onChanged: vi.fn() }} />)
    await screen.findByRole('img', { name: /The other door's/ })
    const row = screen.getByText('Style')
    expect(row.compareDocumentPosition(screen.getByText('Your CV')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    h.call.mockClear()
    await userEvent.type(editor(), '- SQL{Enter}')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(h.call).toHaveBeenCalledWith('show_style', {}))
  })

  it('is not there without the app telling it how the build stands', async () => {
    await open()
    expect(screen.queryByText('Style')).toBeNull()
  })
})
