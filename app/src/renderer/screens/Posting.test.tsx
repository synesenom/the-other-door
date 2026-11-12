// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Posting } from './Posting'
import { waitFor } from '@testing-library/react'
import { mockDoor, stubNarrow } from '../testing'
import { RemoteContext } from '../remote'

afterEach(cleanup)

const full = {
  id: 'jobindex.1',
  title: 'Dataanalytiker',
  title_en: 'Data Analyst',
  company: 'Acme',
  location: 'Copenhagen',
  url: 'https://example.com/job/1',
  description: 'You will analyse data.',
  score: 0.91,
  score_reason: 'Strong match on SQL.',
  language: 'da',
  language_requirement: 'required',
  matching_skills: ['SQL', 'Python'],
  missing_skills: ['Spark'],
  status: 'unapplied',
  history: [],
  materials: null,
  output_dir: '/Users/x/jobs/output/jobindex.1',
}

describe('Posting', () => {
  it('loads the posting by id and shows what it has', async () => {
    const { call } = mockDoor({ show: full })
    render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    expect(await screen.findByRole('heading', { name: 'Dataanalytiker' })).toBeInTheDocument()
    expect(call).toHaveBeenCalledWith('show', { job_id: 'jobindex.1' })
    expect(screen.getByText('Data Analyst')).toBeInTheDocument()
    expect(screen.getByText('Acme · Copenhagen')).toBeInTheDocument()
    expect(screen.getByText('0.91')).toBeInTheDocument()
    expect(screen.getByText('Danish — required')).toBeInTheDocument()
    expect(screen.getByText('You will analyse data.')).toBeInTheDocument()
  })

  it('shows the saved salary estimate, and never asks for one', async () => {
    const { call } = mockDoor({ show: { ...full, salary: { low: 55000, high: 70000, currency: 'DKK', period: 'month', gross: true, position: 'within', basis: '', sources: [{ title: 'Stats', url: 'https://example.com/stats' }], ad_salary: null, as_of: '2026-11-07T10:00:00+00:00' } } })
    render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    expect(await screen.findByText('55,000–70,000 DKK a month, gross')).toBeInTheDocument()
    expect(call).not.toHaveBeenCalledWith('salary_estimate', expect.anything())
  })

  it('leaves out what the posting does not have', async () => {
    mockDoor({ show: { ...full, title_en: null, score_reason: undefined, language: undefined, language_requirement: null, matching_skills: [], missing_skills: [], url: '' } })
    render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    await screen.findByRole('heading', { name: 'Dataanalytiker' })
    expect(screen.queryByText(/why it fits/i)).toBeNull()
    expect(screen.queryByText(/language/i)).toBeNull()
    expect(screen.queryByRole('list', { name: 'Gaps' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Open in browser' })).toBeNull()
  })

  it('names an advantage, and says nothing extra when the requirement is none', async () => {
    mockDoor({ show: { ...full, language: 'en', language_requirement: 'none' } })
    const { container } = render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    expect(await screen.findByText('English')).toBeInTheDocument()
    expect(container.textContent).not.toMatch(/none/i)
    cleanup()
    mockDoor({ show: { ...full, language: 'da', language_requirement: 'advantage' } })
    render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    expect(await screen.findByText('Danish — an advantage')).toBeInTheDocument()
  })

  it('lists the skills the CV covers and the ones it lacks, as words', async () => {
    mockDoor({ show: full })
    render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    expect(await screen.findByRole('list', { name: 'Why it fits' })).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Gaps' })).toBeInTheDocument()
    for (const skill of ['SQL', 'Python', 'Spark']) expect(screen.getByText(skill)).toBeInTheDocument()
  })

  it('marks each skill that fits with a check and each gap with a cross, as Finding jobs marks its sources; no chips', async () => {
    mockDoor({ show: full })
    const { container } = render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    await screen.findByRole('list', { name: 'Why it fits' })
    const item = (skill: string) => screen.getByText(skill).closest('li')!
    for (const skill of ['SQL', 'Python']) {
      expect(item(skill)).toHaveClass('marked', 'skill-fits')
      expect(item(skill).querySelector('.mark polyline')).not.toBeNull() // the check
    }
    expect(item('Spark')).toHaveClass('marked', 'skill-gap')
    expect(item('Spark').querySelector('.mark path')).not.toBeNull() // the cross
    expect(container.querySelector('.columns .chip')).toBeNull()
    expect(container.querySelector('.columns h3')).toBeNull() // the marks say which is which; the names are for screen readers
  })

  it('on the phone, the skills that fit and the gaps too', async () => {
    mockDoor({ show: full })
    render(
      <RemoteContext.Provider value={true}>
        <Posting jobId="jobindex.1" onChanged={() => {}} />
      </RemoteContext.Provider>,
    )
    await screen.findByRole('list', { name: 'Why it fits' })
    expect(screen.getByRole('list', { name: 'Gaps' })).toBeInTheDocument()
  })

  it('shows only the missing list when nothing matches', async () => {
    mockDoor({ show: { ...full, matching_skills: [] } })
    render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    expect(await screen.findByRole('list', { name: 'Gaps' })).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Why it fits' })).toBeNull()
  })

  it('shows no id and no path', async () => {
    mockDoor({ show: full })
    const { container } = render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    await screen.findByRole('heading', { name: 'Dataanalytiker' })
    expect(container.textContent).not.toMatch(/jobindex\.1|\/Users\//)
  })

  it('opens the ad in the system browser through the main process', async () => {
    const { openExternal } = mockDoor({ show: full })
    render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Open in browser' }))
    expect(openExternal).toHaveBeenCalledWith('https://example.com/job/1')
  })

  it("opens the employer's application page when the board's ad links to one", async () => {
    const { openExternal } = mockDoor({ show: { ...full, apply_url: 'https://careers.acme.dk/jobs/42/apply' } })
    render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Apply on careers.acme.dk' }))
    expect(openExternal).toHaveBeenCalledWith('https://careers.acme.dk/jobs/42/apply')
    expect(screen.queryByRole('button', { name: 'Open in browser' })).toBeNull()
  })

  it('names the application host without its www.', async () => {
    mockDoor({ show: { ...full, apply_url: 'https://www.acme.dk/apply/42' } })
    render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    expect(await screen.findByRole('button', { name: 'Apply on acme.dk' })).toBeInTheDocument()
  })

  it('says Loading until the posting is read', async () => {
    let answer: (v: unknown) => void = () => {}
    mockDoor({ show: () => new Promise((r) => (answer = r)) })
    render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    expect(screen.getByText('Loading')).toBeInTheDocument()
    answer(full)
    expect(await screen.findByRole('heading', { name: 'Dataanalytiker' })).toBeInTheDocument()
    expect(screen.queryByText('Loading')).toBeNull()
  })

  it('an apply link that is the ad itself, or not a web link, keeps Open in browser', async () => {
    mockDoor({ show: { ...full, apply_url: 'https://example.com/job/1' } })
    render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    expect(await screen.findByRole('button', { name: 'Open in browser' })).toBeInTheDocument()
    cleanup()
    mockDoor({ show: { ...full, apply_url: 'mailto:jobs@acme.dk' } })
    render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    expect(await screen.findByRole('button', { name: 'Open in browser' })).toBeInTheDocument()
  })

  it('shows an {error} plainly', async () => {
    mockDoor({
      show: () => {
        throw { message: 'no posting found' }
      },
    })
    render(<Posting jobId="jobindex.1" onChanged={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('no posting found')
  })

  it('lays out title, meta, score and its info icon, actions, columns, language, ad in that order', async () => {
    mockDoor({ show: { ...full, posted_at: '2026-10-03', source: 'jobindex' } })
    const { container } = render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    await screen.findByRole('heading', { name: 'Dataanalytiker' })
    const all = [...container.querySelectorAll('*')]
    const at = (el: Element | string) => {
      const found = typeof el === 'string' ? (container.querySelector(el) as Element) : el
      expect(found, String(el)).toBeTruthy()
      return all.indexOf(found)
    }
    const order = [
      at('h2'),
      at(screen.getByText(/^Acme · Copenhagen/)),
      at('.score-l'),
      at(screen.getByRole('button', { name: 'Why this score' })),
      at(screen.getByRole('button', { name: 'Open in browser' })),
      at(screen.getByRole('list', { name: 'Gaps' })),
      at(screen.getByText('Danish — required')),
      at(screen.getByText('You will analyse data.')),
    ]
    expect(order).toEqual([...order].sort((a, b) => a - b))
    expect(new Set(order).size).toBe(order.length)
  })

  it('names the posted date and the site in words in the meta line only when the server sends them', async () => {
    mockDoor({ show: { ...full, posted_at: '2026-10-03', source: 'jobindex', source_name: 'Jobindex' } })
    render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    const meta = await screen.findByText(/^Acme · Copenhagen · /)
    expect(meta).toHaveTextContent(/posted .*3/)
    expect(meta).toHaveTextContent('via Jobindex')
    cleanup()
    // The site's id alone is never shown (words, not ids).
    mockDoor({ show: { ...full, source: 'career_sites', source_name: null } })
    render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    expect(await screen.findByText('Acme · Copenhagen')).toBeInTheDocument()
  })

  it('keeps the reason for the score behind an info icon beside it, shown on hover', async () => {
    mockDoor({ show: { ...full, score_reason: 'Good SQL fit.' } })
    render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    await screen.findByRole('heading', { name: 'Dataanalytiker' })
    expect(screen.queryByText('Good SQL fit.')).toBeNull()
    const icon = screen.getByRole('button', { name: 'Why this score' })
    expect(icon.closest('.score-line')).toHaveTextContent('0.91')
    await userEvent.hover(icon)
    expect(screen.getByRole('tooltip')).toHaveTextContent('Good SQL fit.')
  })

  it('has no info icon without a reason', async () => {
    mockDoor({ show: { ...full, status: 'prepared', score_reason: undefined } })
    render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    await screen.findByRole('heading', { name: 'Dataanalytiker' })
    expect(screen.queryByRole('button', { name: 'Why this score' })).toBeNull()
  })

  it('keeps the title and its meta line together', async () => {
    mockDoor({ show: full })
    const { container } = render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
    await screen.findByRole('heading', { name: 'Dataanalytiker' })
    const head = container.querySelector('.posting-head') as HTMLElement
    expect(head).toBeTruthy()
    expect(head.querySelector('h2')).toBeTruthy()
    expect(head).toHaveTextContent('Acme · Copenhagen')
    expect(head.querySelector('.score-l')).toBeNull()
  })

  describe('the Status control', () => {
    afterEach(() => {
      delete (window as { matchMedia?: unknown }).matchMedia
    })

    it('is a secondary button that opens the status dialog', async () => {
      stubNarrow(false)
      mockDoor({ show: full })
      render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
      const button = await screen.findByRole('button', { name: 'Status' })
      expect(button).toHaveClass('secondary')
      await userEvent.click(button)
      expect(screen.getByRole('dialog', { name: /Status: Data Analyst/ })).toBeInTheDocument()
    })

    it('is in the narrow action bar too', async () => {
      stubNarrow(true)
      mockDoor({ show: full })
      const { container } = render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
      await screen.findByRole('heading', { name: 'Dataanalytiker' })
      await userEvent.click(container.querySelector('.action-bar')!.querySelector('button') as HTMLElement)
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })

    it('Not for me opens the same dialog preset to a reason', async () => {
      stubNarrow(false)
      mockDoor({ show: full })
      render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
      await userEvent.click(await screen.findByRole('button', { name: 'Not for me' }))
      expect(screen.getByLabelText('Why not?')).toBeInTheDocument()
      expect(screen.queryByRole('radio')).toBeNull()
    })

    it('reloads the posting after a save and tells the caller', async () => {
      stubNarrow(false)
      let status = 'unapplied'
      const { call } = mockDoor({
        show: () => ({ ...full, status }),
        set_status: () => {
          status = 'applied'
          return { job_id: 'jobindex.1', status: 'applied', current: 'applied' }
        },
      })
      const onChanged = vi.fn()
      render(<Posting jobId="jobindex.1" onChanged={onChanged} />)
      await userEvent.click(await screen.findByRole('button', { name: 'Status' }))
      await userEvent.click(screen.getByRole('radio', { name: 'Applied' }))
      await userEvent.click(screen.getByRole('button', { name: 'Save' }))
      await waitFor(() => expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ status: 'applied' }), 'Data Analyst'))
      expect(screen.queryByRole('dialog')).toBeNull()
      await waitFor(() => expect(call.mock.calls.filter((c) => c[0] === 'show')).toHaveLength(2))
    })

    it.each([
      ['unapplied', 'Not yet applied', {}],
      ['prepared', 'Prepared', {}],
      ['applied', 'Applied', {}],
      ['rejected', 'Rejected', {}],
      ['ghosted', 'Ghosted', {}],
      ['offer', 'Offer', {}],
    ])('can set %s', async (value, word, extra) => {
      stubNarrow(false)
      const { call } = mockDoor({ show: { ...full, status: 'applied' }, set_status: { job_id: 'jobindex.1', status: value } })
      render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
      await userEvent.click(await screen.findByRole('button', { name: 'Status' }))
      await userEvent.click(screen.getByRole('radio', { name: word }))
      await userEvent.click(screen.getByRole('button', { name: 'Save' }))
      await waitFor(() => expect(call).toHaveBeenCalledWith('set_status', { job_id: 'jobindex.1', status: value, ...extra }))
    })

    it('can set an interview kind, and Not for me with a reason', async () => {
      stubNarrow(false)
      const { call } = mockDoor({ show: { ...full, status: 'applied' }, set_status: { job_id: 'jobindex.1', status: 'x' } })
      render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
      await userEvent.click(await screen.findByRole('button', { name: 'Status' }))
      await userEvent.click(screen.getByRole('radio', { name: 'Interview' }))
      await userEvent.click(screen.getByRole('radio', { name: /Assessment/ }))
      await userEvent.click(screen.getByRole('button', { name: 'Save' }))
      await waitFor(() => expect(call).toHaveBeenCalledWith('set_status', { job_id: 'jobindex.1', status: 'interview:assessment' }))
    })
  })

  describe('in a narrow window', () => {
    afterEach(() => {
      delete (window as { matchMedia?: unknown }).matchMedia
    })

    it('puts the actions in a bottom bar: Status, Not for me, Open in browser, then Prepare application as the one ink button', async () => {
      stubNarrow(true)
      mockDoor({ show: full })
      const { container } = render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
      await screen.findByRole('heading', { name: 'Dataanalytiker' })
      const bar = container.querySelector('.action-bar') as HTMLElement
      expect(bar).toBeTruthy()
      const buttons = [...bar.querySelectorAll('button')]
      expect(buttons.map((b) => b.textContent)).toEqual(['Status', 'Not for me', 'Open in browser', 'Prepare application'])
      expect(buttons[0]).toHaveClass('secondary')
      expect(buttons[2]).toHaveClass('secondary')
      expect(buttons[3]).toHaveClass('primary')
      expect(bar.querySelectorAll('.primary')).toHaveLength(1)
      expect(container.querySelector('.actions')).toBeNull()
    })

    it('wide mode keeps the actions inline with no bottom bar', async () => {
      stubNarrow(false)
      mockDoor({ show: full })
      const { container } = render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
      await screen.findByRole('heading', { name: 'Dataanalytiker' })
      expect(container.querySelector('.action-bar')).toBeNull()
      expect(screen.getByRole('button', { name: 'Open in browser' })).toHaveClass('secondary')
    })
  })

  describe('Prepare', () => {
    afterEach(() => {
      vi.useRealTimers()
      delete (window as { matchMedia?: unknown }).matchMedia
    })
    const materials = { output_dir: '/abs/jobs/output/jobindex.1', page_counts: { cv: 2, cover_letter: 1 }, pngs: { cv: [], cover_letter: [] }, pdfs: {}, keywords: [], tailoring: [], cover_letter_words: 300, rendered: false }
    const prepared = { job_id: 'jobindex.1', outcome: 'prepared', output_dir: materials.output_dir, files: [] }

    it.each(['unapplied', 'prepared'])('with no materials and status %s, Prepare application is the one primary button', async (status) => {
      stubNarrow(false)
      mockDoor({ show: { ...full, status } })
      const { container } = render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
      const prepare = await screen.findByRole('button', { name: 'Prepare application' })
      expect(prepare).toHaveClass('primary')
      expect(container.querySelectorAll('.primary')).toHaveLength(1)
      expect(screen.getByRole('button', { name: 'Open in browser' })).toHaveClass('secondary')
      expect(screen.getByRole('button', { name: 'Status' })).toHaveClass('secondary')
      expect(screen.getByRole('button', { name: 'Not for me' })).toHaveClass('quiet')
      expect(screen.queryByRole('button', { name: 'See the application' })).toBeNull()
    })

    it('with materials, See the application is primary and Prepare again is quiet', async () => {
      stubNarrow(false)
      const onOpenMaterials = vi.fn()
      mockDoor({ show: { ...full, status: 'prepared', materials } })
      render(<Posting jobId="jobindex.1" onChanged={() => {}} onOpenMaterials={onOpenMaterials} />)
      const see = await screen.findByRole('button', { name: 'See the application' })
      expect(see).toHaveClass('primary')
      expect(screen.getByRole('button', { name: 'Prepare again' })).toHaveClass('quiet')
      expect(screen.queryByRole('button', { name: 'Prepare application' })).toBeNull()
      // A job with an application is in play: "Not for me" moves into Status, so the row fits on one line.
      expect(screen.queryByRole('button', { name: 'Not for me' })).toBeNull()
      expect(screen.getByRole('button', { name: 'Status' })).toBeInTheDocument()
      await userEvent.click(see)
      expect(onOpenMaterials).toHaveBeenCalled()
    })

    it('a sent application opens as See what you sent, with no Prepare again', async () => {
      stubNarrow(false)
      const onOpenMaterials = vi.fn()
      mockDoor({ show: { ...full, status: 'applied', materials: { ...materials, sent: true } } })
      render(<Posting jobId="jobindex.1" onChanged={() => {}} onOpenMaterials={onOpenMaterials} />)
      await userEvent.click(await screen.findByRole('button', { name: 'See what you sent' }))
      expect(onOpenMaterials).toHaveBeenCalled()
      expect(screen.queryByRole('button', { name: 'See the application' })).toBeNull()
      expect(screen.queryByRole('button', { name: 'Prepare again' })).toBeNull()
    })

    it('asks before preparing again, then sends force', async () => {
      stubNarrow(false)
      const { call } = mockDoor({ show: { ...full, status: 'prepared', materials }, prepare: prepared })
      render(<Posting jobId="jobindex.1" onChanged={() => {}} onOpenMaterials={() => {}} />)
      await userEvent.click(await screen.findByRole('button', { name: 'Prepare again' }))
      const dialog = screen.getByRole('dialog')
      expect(dialog).toHaveTextContent('This replaces the tailored CV and letter, and any revisions.')
      expect(call.mock.calls.some((c) => c[0] === 'prepare')).toBe(false)
      await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
      expect(call.mock.calls.some((c) => c[0] === 'prepare')).toBe(false)
      await userEvent.click(screen.getByRole('button', { name: 'Prepare again' }))
      await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Prepare again' }))
      await waitFor(() => expect(call).toHaveBeenCalledWith('prepare', { job_id: 'jobindex.1', force: true }, expect.any(String)))
    })

    it.each(['applied', 'interview:screening', 'offer', 'rejected', 'ghosted', 'discarded'])('offers no Prepare for %s without materials, and only See the application with them', async (status) => {
      stubNarrow(false)
      mockDoor({ show: { ...full, status } })
      render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
      await screen.findByRole('button', { name: 'Status' })
      expect(screen.queryByRole('button', { name: /prepare/i })).toBeNull()
      expect(screen.queryByRole('button', { name: 'See the application' })).toBeNull()
      cleanup()
      mockDoor({ show: { ...full, status, materials } })
      render(<Posting jobId="jobindex.1" onChanged={() => {}} onOpenMaterials={() => {}} />)
      expect(await screen.findByRole('button', { name: 'See the application' })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /prepare/i })).toBeNull()
    })

    it('passes a call id, shows the step in words with an elapsed timer, and locks the other actions', async () => {
      stubNarrow(false)
      let push: (p: { progress: number; message: string }) => void = () => {}
      let finish: (v: unknown) => void = () => {}
      const { call, onProgress } = mockDoor({ show: full, prepare: () => new Promise((r) => (finish = r)) })
      onProgress.mockImplementation(((_id: string, cb: typeof push) => {
        push = cb
        return () => {}
      }) as never)
      render(<Posting jobId="jobindex.1" onChanged={() => {}} onOpenMaterials={() => {}} />)
      const button = await screen.findByRole('button', { name: 'Prepare application' })
      vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
      fireEvent.click(button)
      await act(async () => {})
      const prepareCall = call.mock.calls.find((c) => c[0] === 'prepare')!
      expect(prepareCall[1]).toEqual({ job_id: 'jobindex.1' })
      expect(typeof prepareCall[2]).toBe('string')
      expect(onProgress).toHaveBeenCalledWith(prepareCall[2], expect.any(Function))
      act(() => push({ progress: 1, message: 'tailoring Acme: Data Analyst · 3m20s elapsed' }))
      expect(screen.getByText('Writing your CV and cover letter')).toBeInTheDocument()
      expect(screen.getByText('You can leave this open; it takes a few minutes.')).toBeInTheDocument()
      await act(async () => {
        vi.advanceTimersByTime(65_000)
      })
      expect(screen.getByText('Elapsed 1:05')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Prepare application' })).toBeNull()
      expect(screen.getByRole('button', { name: 'Status' })).toBeDisabled()
      expect(screen.getByRole('button', { name: 'Not for me' })).toBeDisabled()
      await act(async () => finish(prepared))
    })

    it.each(['prepared', 'skipped'])('opens the materials on %s', async (outcome) => {
      stubNarrow(false)
      const onOpenMaterials = vi.fn()
      mockDoor({ show: full, prepare: { ...prepared, outcome } })
      render(<Posting jobId="jobindex.1" onChanged={() => {}} onOpenMaterials={onOpenMaterials} />)
      await userEvent.click(await screen.findByRole('button', { name: 'Prepare application' }))
      await waitFor(() => expect(onOpenMaterials).toHaveBeenCalled())
    })

    it("shows the tool's error text and lets the user try again", async () => {
      stubNarrow(false)
      const onOpenMaterials = vi.fn()
      mockDoor({ show: full, prepare: () => { throw new Error('tailor step finished but jobs/output/jobindex.1/ is missing: cv.pdf; status left unchanged.') } })
      render(<Posting jobId="jobindex.1" onChanged={() => {}} onOpenMaterials={onOpenMaterials} />)
      await userEvent.click(await screen.findByRole('button', { name: 'Prepare application' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('tailor step finished but jobs/output/jobindex.1/ is missing: cv.pdf')
      expect(onOpenMaterials).not.toHaveBeenCalled()
      expect(screen.getByRole('button', { name: 'Prepare application' })).toBeEnabled()
    })

    it('says another run is in progress without an alert, and polls until the materials appear', async () => {
      stubNarrow(false)
      let withMaterials = false
      const { call } = mockDoor({
        show: () => ({ ...full, status: withMaterials ? 'prepared' : 'unapplied', materials: withMaterials ? materials : null }),
        prepare: () => { throw new Error('another long-running tool (find_jobs or prepare) is already in progress; wait for it to finish before calling again') },
      })
      render(<Posting jobId="jobindex.1" onChanged={() => {}} onOpenMaterials={() => {}} />)
      const button = await screen.findByRole('button', { name: 'Prepare application' })
      vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
      fireEvent.click(button)
      await act(async () => {})
      expect(screen.getByText('Another run is in progress. Try again when it finishes.')).toBeInTheDocument()
      expect(screen.queryByRole('alert')).toBeNull()
      const shows = () => call.mock.calls.filter((c) => c[0] === 'show').length
      const before = shows()
      await act(async () => {
        vi.advanceTimersByTime(5_000)
      })
      expect(shows()).toBe(before + 1)
      withMaterials = true
      await act(async () => {
        vi.advanceTimersByTime(5_000)
      })
      expect(screen.getByRole('button', { name: 'See the application' })).toBeInTheDocument()
      const after = shows()
      await act(async () => {
        vi.advanceTimersByTime(20_000)
      })
      expect(shows()).toBe(after)
    })

    it('stops polling when it unmounts', async () => {
      stubNarrow(false)
      const { call } = mockDoor({
        show: full,
        prepare: () => { throw new Error('a run is in progress, started at 10:00') },
      })
      const { unmount } = render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
      const button = await screen.findByRole('button', { name: 'Prepare application' })
      vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
      fireEvent.click(button)
      await act(async () => {})
      unmount()
      const n = call.mock.calls.length
      await act(async () => {
        vi.advanceTimersByTime(30_000)
      })
      expect(call.mock.calls.length).toBe(n)
    })

    it('shows the preparing state again after a remount while the call is still running', async () => {
      stubNarrow(false)
      let finish: (v: unknown) => void = () => {}
      mockDoor({ show: full, prepare: () => new Promise((r) => (finish = r)) })
      const first = render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
      await userEvent.click(await screen.findByRole('button', { name: 'Prepare application' }))
      first.unmount()
      render(<Posting jobId="jobindex.1" onChanged={() => {}} />)
      expect(await screen.findByText('You can leave this open; it takes a few minutes.')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Prepare application' })).toBeNull()
      await act(async () => finish(prepared))
    })

    it('narrow: the bar has Prepare application as its one ink button', async () => {
      stubNarrow(true)
      mockDoor({ show: { ...full, status: 'prepared', materials } })
      const { container } = render(<Posting jobId="jobindex.1" onChanged={() => {}} onOpenMaterials={() => {}} />)
      await screen.findByRole('button', { name: 'See the application' })
      const bar = container.querySelector('.action-bar') as HTMLElement
      expect(bar.querySelectorAll('.primary')).toHaveLength(1)
      expect(within(bar).getByRole('button', { name: 'See the application' })).toHaveClass('primary')
    })
  })
})
