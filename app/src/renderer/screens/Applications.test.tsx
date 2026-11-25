// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Applications, groupApplications } from './Applications'
import { match, matchesResult, mockDoor, stubNarrow } from '../testing'

afterEach(() => {
  cleanup()
  delete (window as { matchMedia?: unknown }).matchMedia
})

const rows = [
  match({ id: 'jobindex.1', title: 'Offer job', status: 'offer', score: 0.8 }),
  match({ id: 'jobindex.2', title: 'Applied job', status: 'applied', company: 'Globex', location: 'Aarhus', score: 0.7 }),
  match({ id: 'jobindex.3', title: 'Interview job', status: 'interview:technical', score: 0.9 }),
  match({ id: 'jobindex.4', title: 'Prepared job', status: 'prepared', score: 0.6 }),
  match({ id: 'jobindex.5', title: 'Second interview', status: 'interview:screening', score: 0.5 }),
]

const ended = [match({ id: 'jobindex.9', title: 'Rejected job', status: 'rejected' })]

function setup(list: unknown[] = rows, extra: Record<string, unknown> = {}, closed: unknown[] = []) {
  return mockDoor({
    list_matches: (a: Record<string, unknown>) => matchesResult(a['closed'] ? closed : list),
    show: (args: Record<string, unknown>) => ({ ...(list as { id: string }[]).find((r) => r.id === args.job_id), description: 'd', url: '' }),
    status_summary: {},
    ...extra,
  })
}

describe('groupApplications', () => {
  it('orders Prepared, Applied, Interviewing, Offer and drops the empty ones', () => {
    const groups = groupApplications(rows as never)
    expect(groups.map((g) => g.heading)).toEqual(['Prepared', 'Applied', 'Interviewing', 'Offer'])
    expect(groups[2].rows.map((r) => r.id)).toEqual(['jobindex.3', 'jobindex.5'])
    expect(groupApplications([rows[1]] as never).map((g) => g.heading)).toEqual(['Applied'])
  })
})

describe('Applications', () => {
  it('asks for what is in play and what ended, and shows five columns with their counts', async () => {
    stubNarrow(false)
    const { call } = setup(rows, {}, ended)
    render(<Applications />)
    await screen.findByText('Prepared job')
    expect(call).toHaveBeenCalledWith('list_matches', { ongoing: true })
    expect(call).toHaveBeenCalledWith('list_matches', { closed: true })
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)
    expect(headings).toEqual(['Prepared', 'Applied', 'Interviewing', 'Offer', 'Closed'])
    const interviewing = within(screen.getByRole('region', { name: 'Interviewing' }))
    expect(interviewing.getByRole('heading', { level: 2 }).parentElement).toHaveTextContent(/^Interviewing · 2$/)
    expect(screen.getByText('5 in play · 2 in interviews')).toBeInTheDocument()
  })

  it('narrow: a grouped list, Offer first, empty groups left out, Closed at the end', async () => {
    stubNarrow(true)
    setup(rows.filter((r) => (r as { status: string }).status !== 'offer'), {}, ended)
    render(<Applications />)
    await screen.findByText('Prepared job')
    expect(screen.getByRole('group', { name: 'Applications' })).toHaveClass('board-list')
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(['Interviewing', 'Applied', 'Prepared', 'Closed'])
    expect(screen.getByRole('button', { name: /Rejected job/ })).toBeInTheDocument()
  })

  it('each column opens with its heavy-ruled head', async () => {
    stubNarrow(false)
    setup([match({ id: 'jobindex.1', title: 'Prepared job', status: 'prepared' })])
    const { container } = render(<Applications />)
    await screen.findByText('Prepared job')
    const heads = container.querySelectorAll('.board-column-head')
    expect(heads.length).toBeGreaterThan(0)
    for (const head of heads) expect(head).toHaveClass('rule-heavy')
  })

  it('a card is the title, the company and a note; no score, no id', async () => {
    stubNarrow(false)
    setup([match({ id: 'jobindex.3', title: 'Interview job', company: 'Novo', status: 'interview:technical', rounds: [{ stage: 'screening', result: 'passed' }, { stage: 'technical', result: 'pending' }] })])
    render(<Applications />)
    const card = await screen.findByRole('button', { name: /Interview job/ })
    expect(card).toHaveTextContent('Novo')
    expect(card).toHaveTextContent('technical')
    expect(card.querySelectorAll('.round-dot')).toHaveLength(1)
    expect(card).toHaveTextContent('1 round passed:')
    expect(card).not.toHaveTextContent('0.9')
    expect(card).not.toHaveTextContent('jobindex')
  })

  describe('a card quiet too long', () => {
    const stalled = match({ id: 'jobindex.2', title: 'Silent job', company: 'Globex', status: 'applied', stalled_days: 45 })
    const quiet = match({ id: 'jobindex.6', title: 'Quiet job', status: 'applied', stalled_days: null })

    it('has the warning mark with its words, and no time on any card', async () => {
      stubNarrow(false)
      setup([stalled, quiet])
      render(<Applications />)
      const card = await screen.findByRole('button', { name: /Silent job/ })
      expect(within(card).getByRole('img', { name: 'No answer in 45 days' })).toBeInTheDocument()
      const other = screen.getByRole('button', { name: /Quiet job/ })
      expect(within(other).queryByRole('img')).toBeNull()
      expect(other).not.toHaveTextContent(/ago|today|yesterday/)
    })

    it('narrow: the grouped list has the mark too', async () => {
      stubNarrow(true)
      setup([stalled, quiet])
      render(<Applications />)
      const card = await screen.findByRole('button', { name: /Silent job/ })
      expect(within(card).getByRole('img', { name: 'No answer in 45 days' })).toBeInTheDocument()
    })

    it('a tap anywhere on a card, its warning line too, opens it', async () => {
      // a phone shows the mark's words on the card already: the line is part of the card, never a control of its own
      stubNarrow(true)
      const { call } = setup([stalled, quiet])
      render(<Applications />)
      const card = await screen.findByRole('button', { name: /Silent job/ })
      fireEvent.click(within(card).getByRole('img', { name: 'No answer in 45 days' }))
      await waitFor(() => expect(call).toHaveBeenCalledWith('show', expect.anything()))
    })
  })

  it('Closed shows its cards', async () => {
    stubNarrow(false)
    setup(rows, {}, ended)
    render(<Applications />)
    await screen.findByText('Prepared job')
    expect(screen.getByRole('button', { name: /Rejected job/ })).toHaveTextContent('rejected')
  })

  it('a card opens its posting full width; ← Applications goes back to the board', async () => {
    stubNarrow(false)
    const onPushed = vi.fn()
    const { call } = setup()
    render(<Applications onPushed={onPushed} />)
    await userEvent.click(await screen.findByRole('button', { name: /Applied job/ }))
    await waitFor(() => expect(call).toHaveBeenCalledWith('show', { job_id: 'jobindex.2' }))
    expect(await screen.findByRole('button', { name: 'Status…' })).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Applications board' })).toBeNull()
    expect(onPushed).not.toHaveBeenCalledWith(true) // the sidebar stays on a wide window
    await userEvent.click(screen.getByRole('button', { name: '← Applications' }))
    expect(await screen.findByRole('group', { name: 'Applications board' })).toBeInTheDocument()
  })

  it("the phone's Back goes from a posting to the board", async () => {
    stubNarrow(true)
    setup()
    render(<Applications />)
    await userEvent.click(await screen.findByRole('button', { name: /Applied job/ }))
    expect(await screen.findByRole('button', { name: 'Status…' })).toBeInTheDocument()
    history.back()
    expect(await screen.findByRole('group', { name: 'Applications' })).toBeInTheDocument() // the phone's list
  })

  it('narrow: the posting hides the sidebar too', async () => {
    stubNarrow(true)
    const onPushed = vi.fn()
    setup()
    render(<Applications onPushed={onPushed} />)
    await userEvent.click(await screen.findByRole('button', { name: /Applied job/ }))
    expect(await screen.findByRole('button', { name: '← Applications' })).toBeInTheDocument()
    expect(onPushed).toHaveBeenLastCalledWith(true)
    await userEvent.click(screen.getByRole('button', { name: '← Applications' }))
    expect(await screen.findByText('Prepared job')).toBeInTheDocument()
    expect(onPushed).toHaveBeenLastCalledWith(false)
  })

  it('says what to do when nothing is in play', async () => {
    stubNarrow(false)
    setup([])
    render(<Applications />)
    expect(await screen.findByText('Nothing in play yet. Mark a match Prepared or Applied and it shows here.')).toBeInTheDocument()
  })

  it('a status change goes back to the board, says so and reads the board again', async () => {
    stubNarrow(false)
    let list = rows
    const { call } = setup(undefined, {
      list_matches: (a: Record<string, unknown>) => matchesResult(a['closed'] ? [] : list),
      set_status: (a: Record<string, unknown>) => {
        list = list.filter((r) => r.id !== a.job_id)
        return { job_id: a.job_id, status: a.status, current: a.status }
      },
    })
    render(<Applications />)
    await userEvent.click(await screen.findByRole('button', { name: /Applied job/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Status…' }))
    await userEvent.click(screen.getByRole('radio', { name: 'Not for me' }))
    await userEvent.type(screen.getByLabelText('Why not?'), 'gone')
    call.mockClear()
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(call).toHaveBeenCalledWith('list_matches', { ongoing: true }))
    await waitFor(() => expect(screen.queryByRole('button', { name: /Applied job/ })).toBeNull())
    expect(screen.getByRole('group', { name: 'Applications board' })).toBeInTheDocument()
  })

  it('shows an error as an alert', async () => {
    stubNarrow(false)
    mockDoor({
      list_matches: () => {
        throw { message: 'no jobs folder' }
      },
    })
    render(<Applications />)
    expect(await screen.findByRole('alert')).toHaveTextContent('no jobs folder')
  })

  describe('the prepared application', () => {
    const materials = {
      output_dir: '/abs/jobs/output/jobindex.1',
      pdfs: { cv: '/abs/jobs/output/jobindex.1/cv.pdf', cover_letter: '/abs/jobs/output/jobindex.1/cover_letter.pdf' },
      pngs: { cv: ['/abs/jobs/output/jobindex.1/cv_page_1.png'], cover_letter: ['/abs/jobs/output/jobindex.1/cover_letter_page_1.png'] },
      keywords: [],
      tailoring: [],
      page_counts: { cv: 1, cover_letter: 1 }, cv_max_pages: 2,
      cover_letter_words: 300,
      rendered: false,
      revisable: true,
    }

    it('a Prepared card opens Ready to send; ← Applications returns to the board', async () => {
      stubNarrow(false)
      mockDoor({
        list_matches: (a: Record<string, unknown>) => matchesResult(a['closed'] ? [] : [rows[3]]),
        show: { id: 'jobindex.4', title: 'Prepared job', company: 'Acme', status: 'prepared', materials },
        status_summary: {},
      })
      render(<Applications />)
      await userEvent.click(await screen.findByRole('button', { name: /Prepared job/ }))
      expect(await screen.findByRole('heading', { name: 'Ready to send' })).toBeInTheDocument()
      expect(screen.queryByRole('heading', { name: 'Applications', level: 1 })).toBeNull()
      expect(screen.queryByRole('button', { name: '← Posting' })).toBeNull()
      // the posting (Status, Prepare again) is one click away, and back still returns to the board
      await userEvent.click(screen.getByRole('button', { name: 'See the posting' }))
      expect(await screen.findByRole('heading', { name: 'Prepared job', level: 2 })).toBeInTheDocument()
      await userEvent.click(screen.getByRole('button', { name: '← Applications' }))
      expect(await screen.findByRole('heading', { name: 'Applications', level: 1 })).toBeInTheDocument()
    })

    it('a card of another column still opens the posting', async () => {
      stubNarrow(false)
      const { call } = setup()
      render(<Applications />)
      await userEvent.click(await screen.findByRole('button', { name: /Applied job/ }))
      await waitFor(() => expect(call).toHaveBeenCalledWith('show', { job_id: 'jobindex.2' }))
      expect(screen.queryByRole('heading', { name: 'Ready to send' })).toBeNull()
    })

    it("narrow: I've applied shows the notice and the list", async () => {
      stubNarrow(true)
      const { call } = mockDoor({
        list_matches: (a: Record<string, unknown>) => matchesResult(a['closed'] ? [] : [rows[3]]),
        show: { id: 'jobindex.4', title: 'Prepared job', company: 'Acme', status: 'prepared', materials },
        set_status: { job_id: 'jobindex.4', status: 'applied', current: 'applied' },
        status_summary: {},
      })
      render(<Applications />)
      await userEvent.click(await screen.findByRole('button', { name: /Prepared job/ }))
      const applied = await screen.findByRole('button', { name: "I've applied" })
      call.mockClear()
      await userEvent.click(applied)
      expect(await screen.findByText(/Applied: Prepared job\. It is in Applications now\./)).toBeInTheDocument()
      expect(call).toHaveBeenCalledWith('list_matches', { ongoing: true })
    })
  })
})
