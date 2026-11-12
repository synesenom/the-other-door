// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Materials } from './Materials'
import { mockDoor, stubNarrow } from '../testing'

afterEach(cleanup)

const dir = '/abs/jobs/output/jobindex.1'
const materials = (over: Record<string, unknown> = {}) => ({
  output_dir: dir,
  pdfs: { cv: `${dir}/cv.pdf`, cover_letter: `${dir}/cover_letter.pdf` },
  pngs: { cv: [`${dir}/cv_page_1.png`, `${dir}/cv_page_2.png`], cover_letter: [`${dir}/cover_letter_page_1.png`] },
  keywords: ['SQL', 'dashboards'],
  tailoring: ['Led with the BI project', 'Cut the retail job'],
  page_counts: { cv: 2, cover_letter: 1 },
  cover_letter_words: 310,
  rendered: false,
  file_names: { cv: 'Jane Doe - CV.pdf', cover_letter: 'Jane Doe - Cover letter.pdf' },
  ...over,
})
const posting = (over: Record<string, unknown> = {}) => ({
  id: 'jobindex.1',
  title: 'Dataanalytiker',
  title_en: 'Data Analyst',
  company: 'Acme',
  status: 'prepared',
  materials: materials(),
  ...over,
})
const noop = () => {}
const claim = { kind: 'number', value: '87%', context: 'Cut forecast error by 87%', file: 'cv' }
/** The document shown: one at a time. */
const figure = () => screen.getByRole('figure')
/** Shows that document: one at a time, picked by the switch above the pages (it also picks what Revise changes). */
const pick = (which: 'CV' | 'Letter') => userEvent.click(screen.getByRole('button', { name: new RegExp(`^${which} · `) }))

describe('Materials', () => {
  it('titles the view and shows one document at a time from the door-file scheme, the letter first', async () => {
    mockDoor({ show: posting() })
    render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
    expect(await screen.findByRole('heading', { name: 'Ready to send' })).toBeInTheDocument()
    expect(screen.getByText('Data Analyst · Acme')).toBeInTheDocument()
    expect(document.querySelector('.dash')).toBeNull() // no blue bar above the title
    expect(screen.getAllByRole('figure')).toHaveLength(1)
    const srcs = () => screen.getAllByRole('img').map((i) => i.getAttribute('src'))
    expect(srcs()).toEqual(['door-file://output/jobindex.1/cover_letter_page_1.png?v=0'])
    await pick('CV')
    expect(srcs()).toEqual(['door-file://output/jobindex.1/cv_page_1.png?v=0', 'door-file://output/jobindex.1/cv_page_2.png?v=0'])
  })

  it('has one document switch, in both widths, naming each document with its size', async () => {
    mockDoor({ show: posting() })
    render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
    await screen.findByRole('heading', { name: 'Ready to send' })
    expect(screen.getAllByRole('group', { name: 'Document' })).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'CV · 2 pages' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: 'Letter · 310 words' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('shows the salary estimate prepare saved, and nothing without one', async () => {
    mockDoor({ show: posting({ salary: { low: 55000, high: 70000, currency: 'DKK', period: 'month', gross: true, position: 'within', basis: '', sources: [{ title: 'Stats', url: 'https://example.com/stats' }], ad_salary: null, as_of: '2026-11-07T10:00:00+00:00' } }) })
    render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
    expect(await screen.findByText('55,000–70,000 DKK a month, gross')).toBeInTheDocument()
    cleanup()
    mockDoor({ show: posting({ salary: null }) })
    render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
    await screen.findByRole('heading', { name: 'Ready to send' })
    expect(screen.queryByRole('region', { name: 'Salary' })).toBeNull()
  })

  it('falls back to the original title when there is no English one', async () => {
    mockDoor({ show: posting({ title_en: null }) })
    render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
    expect(await screen.findByText('Dataanalytiker · Acme')).toBeInTheDocument()
  })

  it('says in words when the CV or the letter is over its limit', async () => {
    mockDoor({ show: posting({ materials: materials({ page_counts: { cv: 3, cover_letter: 2 }, pngs: { cv: ['a_page_1.png', 'a_page_2.png', 'a_page_3.png'].map((n) => `${dir}/cv_${n.slice(2)}`), cover_letter: [`${dir}/cover_letter_page_1.png`, `${dir}/cover_letter_page_2.png`] } }) }) })
    render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
    await screen.findByRole('heading', { name: 'Ready to send' })
    expect(within(figure()).getByRole('note')).toHaveTextContent('(limit is 1)')
    await pick('CV')
    expect(within(figure()).getByRole('note')).toHaveTextContent('(limit is 2)')
  })

  it.each([200, 400])('flags a letter of %i words', async (words) => {
    mockDoor({ show: posting({ materials: materials({ cover_letter_words: words }) }) })
    render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
    await screen.findByRole('heading', { name: 'Ready to send' })
    expect(within(figure()).getByRole('note')).toHaveTextContent('(aim for 250–350)')
  })

  it('does not render a stale image past the page count', async () => {
    mockDoor({ show: posting({ materials: materials({ pngs: { cv: [`${dir}/cv_page_1.png`, `${dir}/cv_page_2.png`, `${dir}/cv_page_3.png`], cover_letter: [`${dir}/cover_letter_page_1.png`] } }) }) })
    render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
    await screen.findByRole('heading', { name: 'Ready to send' })
    await pick('CV')
    expect(screen.getAllByRole('img')).toHaveLength(2)
    expect(screen.queryByAltText('CV, page 3')).toBeNull()
  })

  it('saves the document shown under its own name, and says where it went', async () => {
    const { saveMaterial } = mockDoor({ show: posting() })
    render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
    await screen.findByRole('heading', { name: 'Ready to send' })
    expect(screen.queryAllByRole('note')).toHaveLength(0) // no caption repeating the switch
    const save = within(figure()).getByRole('button', { name: 'Save letter' })
    expect(save).toHaveClass('secondary') // bordered, as Find new jobs
    await userEvent.click(save)
    expect(saveMaterial).toHaveBeenLastCalledWith('jobindex.1', 'cover_letter', false, 'Jane Doe - Cover letter.pdf')
    expect(await screen.findByRole('status')).toHaveTextContent('Saved as Jane Doe - Cover letter.pdf in Downloads.')
    await pick('CV')
    await userEvent.click(within(figure()).getByRole('button', { name: 'Save CV' }))
    expect(saveMaterial).toHaveBeenLastCalledWith('jobindex.1', 'cv', false, 'Jane Doe - CV.pdf')
  })

  it('the change box names the document it changes, and follows the switch', async () => {
    mockDoor({ show: posting() })
    render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
    await screen.findByRole('heading', { name: 'Ready to send' })
    expect(screen.getByLabelText('Anything to change?')).toHaveAttribute('placeholder', expect.stringMatching(/^Change the letter: /))
    await pick('CV')
    expect(screen.getByLabelText('Anything to change?')).toHaveAttribute('placeholder', expect.stringMatching(/^Change the CV: /))
  })

  it('a cancelled save says nothing', async () => {
    const { saveMaterial } = mockDoor({ show: posting() })
    saveMaterial.mockResolvedValueOnce({ ok: false, canceled: true })
    render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
    await screen.findByRole('heading', { name: 'Ready to send' })
    await userEvent.click(screen.getByRole('button', { name: 'Save letter' }))
    await waitFor(() => expect(saveMaterial).toHaveBeenCalled())
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  describe('claims the CV does not back', () => {
    it('names them under the title, each once, before it is sent', async () => {
      mockDoor({ show: posting({ materials: materials({ unsupported: [claim, { ...claim, file: 'cover_letter' }, { kind: 'employer', value: 'Nordwind', context: 'Nordwind, 2019', file: 'cv' }] }) }) })
      render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
      await screen.findByRole('heading', { name: 'Ready to send' })
      expect(screen.getByText('Not in your CV: 87%, Nordwind. Check them before you send it.')).toBeInTheDocument()
    })

    it.each([[[]], [null]])('says nothing when the list is %j', async (unsupported) => {
      mockDoor({ show: posting({ materials: materials({ unsupported }) }) })
      render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
      await screen.findByRole('heading', { name: 'Ready to send' })
      expect(screen.queryByText(/Not in your CV/)).toBeNull()
    })
  })

  describe('sent', () => {
    afterEach(() => {
      delete (window as { matchMedia?: unknown }).matchMedia
    })
    const sentDir = `${dir}/sent`
    const sent = () =>
      posting({
        status: 'interview:screening',
        materials: materials({
          sent: true,
          output_dir: sentDir,
          pdfs: { cv: `${sentDir}/cv.pdf`, cover_letter: `${sentDir}/cover_letter.pdf` },
          pngs: { cv: [`${sentDir}/cv_page_1.png`, `${sentDir}/cv_page_2.png`], cover_letter: [`${sentDir}/cover_letter_page_1.png`] },
        }),
      })

    it('shows what was sent, read only: its pages from the sent copy, no Revise and no I have applied', async () => {
      stubNarrow(false)
      mockDoor({ show: sent() })
      render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
      expect(await screen.findByRole('heading', { name: 'What you sent' })).toBeInTheDocument()
      expect(screen.getAllByRole('img').map((i) => i.getAttribute('src'))).toEqual(['door-file://output/jobindex.1/sent/cover_letter_page_1.png?v=0'])
      expect(screen.queryByRole('button', { name: 'Revise' })).toBeNull()
      expect(screen.queryByRole('button', { name: 'Undo last change' })).toBeNull()
      expect(screen.queryByRole('button', { name: "I've applied" })).toBeNull()
    })

    it('saves the sent copy', async () => {
      stubNarrow(false)
      const { saveMaterial } = mockDoor({ show: sent() })
      render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
      await screen.findByRole('heading', { name: 'What you sent' })
      await userEvent.click(within(figure()).getByRole('button', { name: 'Save letter' }))
      expect(saveMaterial).toHaveBeenCalledWith('jobindex.1', 'cover_letter', true, 'Jane Doe - Cover letter.pdf')
    })

    it('without the sent copy, shows and saves the working files of its own job', async () => {
      stubNarrow(false)
      const { saveMaterial } = mockDoor({ show: posting({ status: 'applied', materials: materials({ sent: true }) }) })
      render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
      await screen.findByRole('heading', { name: 'What you sent' })
      expect(screen.getAllByRole('img').map((i) => i.getAttribute('src'))).toEqual(['door-file://output/jobindex.1/cover_letter_page_1.png?v=0'])
      await userEvent.click(within(figure()).getByRole('button', { name: 'Save letter' }))
      expect(saveMaterial).toHaveBeenCalledWith('jobindex.1', 'cover_letter', false, 'Jane Doe - Cover letter.pdf')
    })

    it('says nothing of claims: they were for before it went out', async () => {
      stubNarrow(false)
      mockDoor({ show: posting({ status: 'applied', materials: materials({ sent: true, unsupported: [claim] }) }) })
      render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
      await screen.findByRole('heading', { name: 'What you sent' })
      expect(screen.queryByText(/Not in your CV/)).toBeNull()
    })

    it('narrow: only Save in the action bar', async () => {
      stubNarrow(true)
      mockDoor({ show: sent() })
      render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
      await screen.findByRole('heading', { name: 'What you sent' })
      expect(screen.getByRole('button', { name: 'Save letter' })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: "I've applied" })).toBeNull()
    })
  })

  it('shows an error when a PDF cannot be saved', async () => {
    const { saveMaterial } = mockDoor({ show: posting() })
    saveMaterial.mockResolvedValueOnce({ ok: false, error: 'Could not save it: disk full' })
    render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
    await screen.findByRole('heading', { name: 'Ready to send' })
    await userEvent.click(within(figure()).getByRole('button', { name: 'Save letter' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not save it: disk full')
  })

  it('goes back through the link', async () => {
    mockDoor({ show: posting() })
    const onBack = vi.fn()
    render(<Materials jobId="jobindex.1" onBack={onBack} onApplied={noop} />)
    await userEvent.click(await screen.findByRole('button', { name: '← Posting' }))
    expect(onBack).toHaveBeenCalled()
  })

  it('shows a load error', async () => {
    mockDoor({ show: () => { throw new Error('no such job') } })
    render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('no such job')
  })

  describe('revise', () => {
    const revisedShow = () => {
      let n = 0
      return () => (++n === 1 ? posting() : posting({ materials: materials({ page_counts: { cv: 2, cover_letter: 1 }, cover_letter_words: 280 }) }))
    }

    it('applies to the letter by default and is off while the text is empty', async () => {
      mockDoor({ show: posting() })
      render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
      await screen.findByRole('heading', { name: 'Ready to send' })
      expect(screen.getByRole('button', { name: /^Letter · / })).toHaveAttribute('aria-pressed', 'true')
      expect(screen.getByRole('button', { name: 'Revise' })).toBeDisabled()
      await userEvent.type(screen.getByLabelText('Anything to change?'), 'shorter')
      expect(screen.getByRole('button', { name: 'Revise' })).toBeEnabled()
    })

    it('sends the instruction, reloads the posting, bumps the image version, and says nothing', async () => {
      const { call } = mockDoor({
        show: revisedShow(),
        revise: { outcome: 'revised', job_id: 'jobindex.1', file: `${dir}/cover_letter.tex`, compile: [{ file: 'cover_letter.tex', status: 'compiled' }] },
      })
      render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
      await screen.findByRole('heading', { name: 'Ready to send' })
      await pick('CV')
      await userEvent.type(screen.getByLabelText('Anything to change?'), 'cut the retail job')
      await userEvent.click(screen.getByRole('button', { name: 'Revise' }))
      await waitFor(() => expect(call.mock.calls.filter((c) => c[0] === 'show')).toHaveLength(2))
      expect(call).toHaveBeenCalledWith('revise', { job_id: 'jobindex.1', file: 'cv', instruction: 'cut the retail job' })
      await waitFor(() => expect(screen.getAllByRole('img')[0]).toHaveAttribute('src', expect.stringContaining('?v=1')))
      expect(screen.queryByRole('status')).toBeNull()
      expect(screen.getAllByRole('img')[0]).toHaveAttribute('src', expect.stringContaining('?v=1'))
      expect(screen.getByLabelText('Anything to change?')).toHaveValue('')
    })

    it('keeps the old pages and shows the error when revise fails', async () => {
      const { call } = mockDoor({ show: posting(), revise: () => { throw new Error('claude did not answer') } })
      render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
      await screen.findByRole('heading', { name: 'Ready to send' })
      await userEvent.type(screen.getByLabelText('Anything to change?'), 'warmer')
      await userEvent.click(screen.getByRole('button', { name: 'Revise' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('claude did not answer')
      expect(call.mock.calls.filter((c) => c[0] === 'show')).toHaveLength(1)
      expect(screen.getAllByRole('img')[0]).toHaveAttribute('src', expect.stringContaining('?v=0'))
      expect(screen.getByLabelText('Anything to change?')).toHaveValue('warmer')
    })

    it('says the PDF was not rebuilt when LaTeX failed, and keeps the old pages', async () => {
      const { call } = mockDoor({
        show: posting(),
        revise: { outcome: 'revised', job_id: 'jobindex.1', file: 'x', compile: [{ file: 'cover_letter.tex', status: 'error', stderr: 'boom' }] },
      })
      render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
      await screen.findByRole('heading', { name: 'Ready to send' })
      await userEvent.type(screen.getByLabelText('Anything to change?'), 'x')
      await userEvent.click(screen.getByRole('button', { name: 'Revise' }))
      expect(
        await screen.findByText(
          'The change was made but the PDF could not be rebuilt, so the pages still show the previous version. Undo last change puts it back.',
        ),
      ).toBeInTheDocument()
      expect(call.mock.calls.filter((c) => c[0] === 'show')).toHaveLength(1)
      expect(screen.getAllByRole('img')[0]).toHaveAttribute('src', expect.stringContaining('?v=0'))
    })

    it('undoes the last change and reloads', async () => {
      const { call } = mockDoor({ show: revisedShow(), revise: { outcome: 'undone', job_id: 'jobindex.1', file: 'x', compile: [] } })
      render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
      await screen.findByRole('heading', { name: 'Ready to send' })
      await userEvent.click(screen.getByRole('button', { name: 'Undo last change' }))
      await waitFor(() => expect(call.mock.calls.filter((c) => c[0] === 'show')).toHaveLength(2))
      expect(call).toHaveBeenCalledWith('revise', { job_id: 'jobindex.1', file: 'cover_letter', undo: true })
      expect(screen.queryByRole('status')).toBeNull()
    })

    it('treats nothing to undo as a quiet notice, not an alert', async () => {
      mockDoor({ show: posting(), revise: () => { throw new Error('nothing to undo: no cover_letter.tex.bak') } })
      render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
      await screen.findByRole('heading', { name: 'Ready to send' })
      await userEvent.click(screen.getByRole('button', { name: 'Undo last change' }))
      expect(await screen.findByText('Nothing to undo.')).toBeInTheDocument()
      expect(screen.queryByRole('alert')).toBeNull()
    })

    it('shows Revising and dims the pages while the call runs, with the other actions off', async () => {
      let finish: (v: unknown) => void = noop
      const pending = new Promise((r) => (finish = r))
      mockDoor({ show: posting(), revise: () => pending })
      render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
      await screen.findByRole('heading', { name: 'Ready to send' })
      await userEvent.type(screen.getByLabelText('Anything to change?'), 'x')
      await userEvent.click(screen.getByRole('button', { name: 'Revise' }))
      expect(await screen.findByText('Revising…')).toBeInTheDocument()
      expect(screen.getByTestId('pages')).toHaveAttribute('aria-busy', 'true')
      for (const name of ['Revise', 'Undo last change', "I've applied", 'Save letter']) {
        expect(screen.getByRole('button', { name })).toBeDisabled()
      }
      finish({ outcome: 'revised', job_id: 'jobindex.1', file: 'x', compile: [] })
      await waitFor(() => expect(screen.queryByText('Revising…')).toBeNull())
    })
  })

  describe("I've applied", () => {
    it('records Applied in one click, with no dialog, and reports the saved status', async () => {
      const onApplied = vi.fn()
      const { call } = mockDoor({
        show: posting(),
        set_status: (a: Record<string, unknown>) => ({ job_id: a.job_id, status: a.status }),
      })
      render(<Materials jobId="jobindex.1" onBack={noop} onApplied={onApplied} />)
      await screen.findByRole('heading', { name: 'Ready to send' })
      await userEvent.click(screen.getByRole('button', { name: "I've applied" }))
      expect(screen.queryByRole('dialog')).toBeNull()
      await waitFor(() => expect(onApplied).toHaveBeenCalledWith({ job_id: 'jobindex.1', status: 'applied' }, 'Data Analyst'))
      expect(call).toHaveBeenCalledWith('set_status', { job_id: 'jobindex.1', status: 'applied' })
    })

    it('says why when it cannot be recorded, and stays', async () => {
      const onApplied = vi.fn()
      mockDoor({ show: posting(), set_status: () => { throw new Error('a run is in progress') } })
      render(<Materials jobId="jobindex.1" onBack={noop} onApplied={onApplied} />)
      await screen.findByRole('heading', { name: 'Ready to send' })
      await userEvent.click(screen.getByRole('button', { name: "I've applied" }))
      expect(await screen.findByRole('alert')).toHaveTextContent('a run is in progress')
      expect(onApplied).not.toHaveBeenCalled()
    })
  })

  describe('narrow', () => {
    it('shows one document at a time behind a pill switch and keeps the actions in a bottom bar', async () => {
      stubNarrow(true)
      const { saveMaterial } = mockDoor({ show: posting() })
      render(<Materials jobId="jobindex.1" onBack={noop} onApplied={noop} />)
      expect(await screen.findByRole('button', { name: '← Posting' })).toBeInTheDocument()
      const cv = screen.getByRole('button', { name: 'CV · 2 pages' })
      const letter = screen.getByRole('button', { name: 'Letter · 310 words' })
      expect(letter).toHaveAttribute('aria-pressed', 'true')
      expect(screen.getAllByRole('img')).toHaveLength(1)
      await userEvent.click(cv)
      expect(screen.getAllByRole('img')).toHaveLength(2)
      await userEvent.click(screen.getByRole('button', { name: 'Save CV' }))
      expect(saveMaterial).toHaveBeenCalledWith('jobindex.1', 'cv', false, 'Jane Doe - CV.pdf')
      expect(screen.getByRole('button', { name: "I've applied" })).toBeInTheDocument()
      stubNarrow(false)
    })
  })
})
