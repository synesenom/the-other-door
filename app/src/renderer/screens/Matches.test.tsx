// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Matches } from './Matches'
import { seenHere, unsentSeen } from './seen-store'
import { match, matchesResult, mockDoor, stubNarrow, summary } from '../testing'

afterEach(() => {
  cleanup()
  seenHere.clear()
  unsentSeen.clear()
})

const two = [
  match({ id: 'jobindex.1', title: 'Dataanalytiker', title_en: 'Data Analyst', score: 0.91, is_new: true }),
  match({ id: 'jobindex.2', title: 'BI Developer', company: 'Globex', location: 'Aarhus', score: 0.74, status: 'prepared' }),
]

function setup(extra: Record<string, unknown> = {}, matches: unknown[] = two, listed: Record<string, unknown> = {}) {
  return mockDoor({
    status_summary: summary({ since_last_review: { last_reviewed_at: null, runs: 1, last_run: null, new_matches: 1, site_failures: [] } }),
    list_matches: (args: Record<string, unknown>) =>
      matchesResult(args.new_only ? (matches as { is_new: boolean }[]).filter((m) => m.is_new) : matches, listed),
    show: { id: 'jobindex.1', title: 'Dataanalytiker', company: 'Acme', location: 'Copenhagen', description: 'text', status: 'unapplied' },
    ...extra,
  })
}

describe('Matches, Find new jobs', () => {
  afterEach(() => {
    delete (window as { matchMedia?: unknown }).matchMedia
  })

  it('a narrow window, which has no sidebar foot, has a pill beside Add a job that asks for a run', async () => {
    stubNarrow(true)
    setup()
    const onFindJobs = vi.fn()
    render(<Matches onFindJobs={onFindJobs} />)
    await screen.findAllByRole('listitem')
    const pill = screen.getByRole('button', { name: 'Find new jobs' })
    expect(pill).toHaveClass('pill')
    await userEvent.click(pill)
    expect(onFindJobs).toHaveBeenCalledTimes(1)
  })

  it('a wide window leaves it to the sidebar', async () => {
    stubNarrow(false)
    setup()
    render(<Matches onFindJobs={() => {}} />)
    await screen.findAllByRole('listitem')
    expect(screen.queryByRole('button', { name: 'Find new jobs' })).toBeNull()
  })

  it('is off while a Prepare runs, and says why on hover', async () => {
    stubNarrow(true)
    setup()
    render(<Matches onFindJobs={() => {}} preparing />)
    await screen.findAllByRole('listitem')
    const pill = screen.getByRole('button', { name: 'Find new jobs' })
    expect(pill).toBeDisabled()
    expect(pill).toHaveAccessibleDescription(/Preparing an application/)
  })

  it('reads Finding jobs… while a run is going, and is off when another process runs', async () => {
    stubNarrow(true)
    setup()
    render(<Matches onFindJobs={() => {}} finding="own" />)
    await screen.findAllByRole('listitem')
    expect(screen.getByRole('button', { name: 'Finding jobs…' })).toBeEnabled()
    cleanup()
    render(<Matches onFindJobs={() => {}} finding="elsewhere" />)
    await screen.findAllByRole('listitem')
    expect(screen.getByRole('button', { name: 'Finding jobs…' })).toBeDisabled()
  })

  it('can open on the new matches only', async () => {
    setup()
    render(<Matches newOnlyFirst />)
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(1))
    expect(screen.getByRole('listitem')).toHaveTextContent('Dataanalytiker')
    expect(screen.getByRole('switch', { name: 'New only' })).toHaveAttribute('aria-checked', 'true')
  })

  it('has no pill without a way to start a run', async () => {
    stubNarrow(true)
    setup()
    render(<Matches />)
    await screen.findAllByRole('listitem')
    expect(screen.queryByRole('button', { name: /jobs/ })).toBeNull()
  })
})

describe('Matches', () => {
  it('lists the matches in the order served', async () => {
    setup()
    render(<Matches />)
    const rows = await screen.findAllByRole('listitem')
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText('Dataanalytiker')).toBeInTheDocument()
    expect(within(rows[1]).getByText('BI Developer')).toBeInTheDocument()
  })

  it('shows the English title next to a title in another language', async () => {
    setup()
    render(<Matches />)
    const row = (await screen.findAllByRole('listitem'))[0]
    expect(within(row).getByText('Data Analyst')).toBeInTheDocument()
  })

  it('shows company and place, the score, and a status as a word', async () => {
    setup()
    render(<Matches />)
    const rows = await screen.findAllByRole('listitem')
    expect(within(rows[1]).getByText('Globex · Aarhus')).toBeInTheDocument()
    expect(within(rows[0]).getByText('0.91')).toBeInTheDocument()
    expect(within(rows[1]).getByText('Prepared')).toBeInTheDocument()
    expect(within(rows[0]).queryByText(/unapplied/i)).toBeNull()
  })

  it('marks only a new posting with the new dot', async () => {
    setup()
    render(<Matches />)
    const rows = await screen.findAllByRole('listitem')
    expect(within(rows[0]).getByLabelText('New since your last review')).toBeInTheDocument()
    expect(within(rows[1]).queryByLabelText('New since your last review')).toBeNull()
  })

  it('never puts an id on screen', async () => {
    setup()
    const { container } = render(<Matches />)
    await screen.findAllByRole('listitem')
    expect(container.textContent).not.toMatch(/jobindex\.\d/)
  })

  it('"New only" filters the list at once, asking the server nothing', async () => {
    const { call } = setup()
    render(<Matches />)
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(2))
    await userEvent.click(screen.getByRole('switch', { name: 'New only' }))
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    expect(screen.getByRole('listitem')).toHaveTextContent('Dataanalytiker')
    expect(screen.queryByRole('status')).toBeNull()
    await userEvent.click(screen.getByRole('switch', { name: 'New only' }))
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(call.mock.calls.filter(([tool]) => tool === 'list_matches')).toHaveLength(1)
  })

  it('a new match opened under "New only" stays listed, without its dot, until the switch is turned again', async () => {
    setup({ mark_seen: { job_id: 'jobindex.1' } }, two, { scored: 2, last_reviewed_at: '2026-10-29T08:00:00+00:00' })
    render(<Matches newOnlyFirst />)
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(1))
    await userEvent.click(within(screen.getByRole('listitem')).getByRole('button'))
    await userEvent.click(await screen.findByRole('button', { name: '← Matches' }))
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    expect(screen.queryByLabelText('New since your last review')).toBeNull()
    await userEvent.click(screen.getByRole('switch', { name: 'New only' }))
    await userEvent.click(screen.getByRole('switch', { name: 'New only' }))
    expect(await screen.findByText('Nothing new since your last review.')).toBeInTheDocument()
  })

  it('says nothing was scored only when nothing was', async () => {
    setup({}, [], { scored: 0 })
    render(<Matches />)
    expect(await screen.findByText('Nothing scored yet. Find new jobs to start.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Lower the bar' })).toBeNull()
  })

  it('says nothing was scored when the server does not say how many were', async () => {
    setup({}, [])
    render(<Matches />)
    expect(await screen.findByText(/Nothing scored yet/)).toBeInTheDocument()
  })

  it('with jobs scored below the bar and no review yet, says nothing reached the bar and offers to lower it', async () => {
    setup({}, [], { scored: 40 })
    const onLowerBar = vi.fn()
    render(<Matches newOnlyFirst onLowerBar={onLowerBar} />)
    expect(await screen.findByText('Nothing has reached your bar (65%) yet.')).toBeInTheDocument()
    expect(screen.queryByText(/since your last review/)).toBeNull()
    expect(screen.queryByText(/Nothing scored yet/)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Lower the bar' }))
    expect(onLowerBar).toHaveBeenCalledTimes(1)
  })

  it('after a review, with New only and nothing new, says there is nothing new', async () => {
    setup({}, [], { scored: 40, last_reviewed_at: '2026-10-29T08:00:00+00:00' })
    render(<Matches newOnlyFirst />)
    expect(await screen.findByText('Nothing new since your last review.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Lower the bar' })).toBeNull()
  })

  it('after a review, without New only, nothing at the bar is said as such', async () => {
    setup({}, [], { scored: 40, last_reviewed_at: '2026-10-29T08:00:00+00:00' })
    render(<Matches />)
    expect(await screen.findByText('Nothing has reached your bar (65%) yet.')).toBeInTheDocument()
  })

  it('shows an {error} from the server plainly', async () => {
    setup({
      list_matches: () => {
        throw { message: 'a run is in progress' }
      },
    })
    render(<Matches />)
    expect(await screen.findByRole('alert')).toHaveTextContent('a run is in progress')
  })

  it('shows the list and the heading while status_summary is still pending', async () => {
    setup({ status_summary: () => new Promise(() => {}) })
    render(<Matches />)
    expect(await screen.findAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByRole('heading', { name: 'Matches' })).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'New only' })).toBeInTheDocument()
  })

  it('says Loading as a status until the list arrives', async () => {
    setup()
    render(<Matches />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading')
    await screen.findAllByRole('listitem')
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('says what a run in another process is doing, above the list, in words and not its raw message', async () => {
    const steps = [{ name: 'search', status: 'running', detail: '', done: 1, total: 3 }]
    setup({ status_summary: summary({ in_progress: { purpose: 'run', message: "'data' details", steps } }) })
    render(<Matches />)
    expect(await screen.findAllByRole('listitem')).toHaveLength(2)
    expect(await screen.findByRole('status')).toHaveTextContent('Finding new jobs: searching the job boards (1 of 3)')
    expect(screen.queryByText(/details/)).toBeNull()
  })

  it('keeps the list when status_summary fails, with a quiet notice', async () => {
    setup({
      status_summary: () => {
        throw { message: 'summary broke' }
      },
    })
    render(<Matches />)
    expect(await screen.findAllByRole('listitem')).toHaveLength(2)
    expect(await screen.findByText(/summary broke/)).toHaveClass('notice')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('reloads both calls after a discard', async () => {
    const { call } = setup({ set_status: { status: 'discarded' } })
    render(<Matches />)
    await userEvent.click(within((await screen.findAllByRole('listitem'))[0]).getByRole('button'))
    await userEvent.click(await screen.findByRole('button', { name: 'Not for me' }))
    await userEvent.type(screen.getByLabelText('Why not?'), 'too far')
    call.mockClear()
    await userEvent.click(screen.getByRole('button', { name: 'Discard' }))
    await waitFor(() => expect(call).toHaveBeenCalledWith('list_matches', {}))
    expect(call).toHaveBeenCalledWith('status_summary', {})
  })

  describe('after a status change', () => {
    const three = [
      match({ id: 'jobindex.1', title: 'First job' }),
      match({ id: 'jobindex.2', title: 'Second job' }),
      match({ id: 'jobindex.3', title: 'Third job' }),
    ]

    function changing(result: Record<string, unknown>, gone = true) {
      let rows = three
      const h = setup(
        {
          list_matches: () => matchesResult(rows),
          show: (args: Record<string, unknown>) => ({ ...three.find((r) => r.id === args.job_id), description: 'd', url: '' }),
          set_status: (args: Record<string, unknown>) => {
            if (gone) rows = rows.filter((r) => r.id !== args.job_id)
            return { job_id: args.job_id, status: args.status, current: args.status, ...result }
          },
        },
        three,
      )
      return h
    }

    async function markApplied(row: string) {
      await userEvent.click(await screen.findByRole('button', { name: new RegExp(row) }))
      await userEvent.click(await screen.findByRole('button', { name: 'Status' }))
      await userEvent.click(screen.getByRole('radio', { name: 'Applied' }))
      await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    }

    it('says what happened and where the job went, and refreshes both calls', async () => {
      stubNarrow(false)
      const { call } = changing({})
      render(<Matches />)
      await screen.findAllByRole('listitem')
      call.mockClear()
      await markApplied('Second job')
      expect(await screen.findByText('Applied: Second job. It is in Applications now.')).toBeInTheDocument()
      expect(call).toHaveBeenCalledWith('list_matches', {})
      expect(call).toHaveBeenCalledWith('status_summary', {})
    })

    it('goes back to the list, which marks the row that took its place', async () => {
      stubNarrow(false)
      changing({})
      render(<Matches />)
      await screen.findAllByRole('listitem')
      await markApplied('Second job')
      await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(2))
      const rows = screen.getAllByRole('listitem')
      expect(within(rows[1]).getByRole('button')).toHaveAttribute('aria-current', 'true')
      expect(screen.queryByRole('button', { name: '← Matches' })).toBeNull()
    })

    it('falls back to the last row when the last one went', async () => {
      stubNarrow(false)
      changing({})
      render(<Matches />)
      await screen.findAllByRole('listitem')
      await markApplied('Third job')
      await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(2))
      const rows = screen.getAllByRole('listitem')
      expect(within(rows[1]).getByRole('button')).toHaveAttribute('aria-current', 'true')
    })

    it('Not for me opens the next match in its place, and says what happened', async () => {
      stubNarrow(false)
      const { call } = changing({})
      render(<Matches />)
      await userEvent.click(await screen.findByRole('button', { name: /Second job/ }))
      await userEvent.click(await screen.findByRole('button', { name: 'Not for me' }))
      await userEvent.type(screen.getByLabelText('Why not?'), 'too far')
      await userEvent.click(screen.getByRole('button', { name: 'Discard' }))
      await waitFor(() => expect(call).toHaveBeenCalledWith('show', { job_id: 'jobindex.3' }))
      expect(await screen.findByRole('heading', { name: 'Third job', level: 2 })).toBeInTheDocument()
      expect(screen.getByRole('status')).toHaveClass('notice')
      expect(screen.getByRole('button', { name: '← Matches' })).toBeInTheDocument()
    })

    it('Not for me on the only match left goes back to the list', async () => {
      stubNarrow(false)
      let rows = [three[0]]
      setup({
        list_matches: () => matchesResult(rows),
        show: { ...three[0], description: 'd', url: '' },
        set_status: (args: Record<string, unknown>) => {
          rows = []
          return { job_id: args.job_id, status: 'discarded', current: 'discarded' }
        },
      })
      render(<Matches />)
      await userEvent.click(await screen.findByRole('button', { name: /First job/ }))
      await userEvent.click(await screen.findByRole('button', { name: 'Not for me' }))
      await userEvent.type(screen.getByLabelText('Why not?'), 'too far')
      await userEvent.click(screen.getByRole('button', { name: 'Discard' }))
      expect(await screen.findByText(/Nothing scored yet/)).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: '← Matches' })).toBeNull()
    })

    it('names a job the list does not hold (opened from a notification)', async () => {
      stubNarrow(false)
      setup({
        show: { id: 'jobindex.9', title: 'Elsewhere job', title_en: 'Job from elsewhere', company: 'Initech', status: 'unapplied', description: 'd' },
        set_status: { job_id: 'jobindex.9', status: 'applied', current: 'applied' },
      })
      render(<Matches opening={{ n: 1, target: { screen: 'posting', jobId: 'jobindex.9', inPlay: false } }} />)
      await userEvent.click(await screen.findByRole('button', { name: 'Status' }))
      await userEvent.click(screen.getByRole('radio', { name: 'Applied' }))
      await userEvent.click(screen.getByRole('button', { name: 'Save' }))
      expect(await screen.findByText('Applied: Job from elsewhere. It is in Applications now.')).toBeInTheDocument()
    })

    it('shows a server warning as a notice', async () => {
      stubNarrow(false)
      changing({ warning: 'The ad is only a snippet.' })
      render(<Matches />)
      await markApplied('First job')
      expect(await screen.findByText('The ad is only a snippet.')).toHaveClass('notice')
    })

    it('says "Back in Matches." for unapplied, and a posting that stays in the list stays selected', async () => {
      stubNarrow(false)
      changing({}, false)
      render(<Matches />)
      await userEvent.click(await screen.findByRole('button', { name: /First job/ }))
      await userEvent.click(await screen.findByRole('button', { name: 'Status' }))
      await userEvent.click(screen.getByRole('radio', { name: 'Not yet applied' }))
      await userEvent.click(screen.getByRole('button', { name: 'Save' }))
      expect(await screen.findByText('Back in Matches.')).toBeInTheDocument()
      await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(3))
      expect(within(screen.getAllByRole('listitem')[0]).getByRole('button')).toHaveAttribute('aria-current', 'true')
    })

    it('in a narrow window goes back to the list', async () => {
      stubNarrow(true)
      const onPushed = vi.fn()
      changing({})
      render(<Matches onPushed={onPushed} />)
      await userEvent.click(within((await screen.findAllByRole('listitem'))[1]).getByRole('button'))
      await userEvent.click(await screen.findByRole('button', { name: 'Status' }))
      await userEvent.click(screen.getByRole('radio', { name: 'Applied' }))
      await userEvent.click(screen.getByRole('button', { name: 'Save' }))
      expect(await screen.findByText('Applied: Second job. It is in Applications now.')).toBeInTheDocument()
      await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(2))
      expect(onPushed).toHaveBeenLastCalledWith(false)
      delete (window as { matchMedia?: unknown }).matchMedia
    })
  })

  describe('a match opened is seen', () => {
    it('drops its dot, and tells the server once', async () => {
      const { call } = setup({ mark_seen: { job_id: 'jobindex.1' } }, two, { scored: 2, last_reviewed_at: '2026-10-29T08:00:00+00:00' })
      render(<Matches />)
      await screen.findByLabelText('New since your last review')
      await userEvent.click(within(screen.getAllByRole('listitem')[0]).getByRole('button'))
      await waitFor(() => expect(call).toHaveBeenCalledWith('mark_seen', { job_id: 'jobindex.1' }))
      await userEvent.click(screen.getByRole('button', { name: '← Matches' }))
      await screen.findAllByRole('listitem')
      expect(screen.queryByLabelText('New since your last review')).toBeNull()
      await userEvent.click(within(screen.getAllByRole('listitem')[0]).getByRole('button'))
      await screen.findByRole('button', { name: '← Matches' })
      expect(call.mock.calls.filter(([tool]) => tool === 'mark_seen')).toHaveLength(1)
    })

    it('does not tell the server about a match that was not new', async () => {
      const { call } = setup()
      render(<Matches />)
      await userEvent.click(within((await screen.findAllByRole('listitem'))[1]).getByRole('button'))
      await screen.findByRole('button', { name: '← Matches' })
      expect(call).not.toHaveBeenCalledWith('mark_seen', expect.anything())
    })

    it('stays seen when the server refused it (a run holds the ledger), and says nothing', async () => {
      let refuse = true
      const { call } = setup({
        mark_seen: () => {
          if (refuse) throw { message: 'a run is in progress' }
          return { job_id: 'jobindex.1' }
        },
      })
      render(<Matches />)
      await screen.findByLabelText('New since your last review')
      await userEvent.click(within(screen.getAllByRole('listitem')[0]).getByRole('button'))
      await waitFor(() => expect(call).toHaveBeenCalledWith('mark_seen', { job_id: 'jobindex.1' }))
      await userEvent.click(screen.getByRole('button', { name: '← Matches' }))
      await screen.findAllByRole('listitem')
      expect(screen.queryByLabelText('New since your last review')).toBeNull()
      expect(screen.queryByRole('alert')).toBeNull()
    })

    it('stays seen, and is sent again, when the list is mounted afresh (a run ended)', async () => {
      let refuse = true
      const { call } = setup({
        mark_seen: () => {
          if (refuse) throw { message: 'a run is in progress' }
          return { job_id: 'jobindex.1' }
        },
      })
      render(<Matches />)
      await screen.findByLabelText('New since your last review')
      await userEvent.click(within(screen.getAllByRole('listitem')[0]).getByRole('button'))
      await waitFor(() => expect(call).toHaveBeenCalledWith('mark_seen', { job_id: 'jobindex.1' }))
      cleanup()
      refuse = false
      render(<Matches />)
      await screen.findAllByRole('listitem')
      expect(screen.queryByLabelText('New since your last review')).toBeNull()
      await waitFor(() => expect(call.mock.calls.filter(([tool]) => tool === 'mark_seen')).toHaveLength(2))
    })

  })

  describe('importing an ad', () => {
    const imported = { job_id: 'manual.zz', score: null, score_reason: null, score_error: 'no profile' }
    const showImported = (args: Record<string, unknown>) =>
      args.job_id === 'manual.zz'
        ? { id: 'manual.zz', title: 'Imported Role', company: 'Newco', status: 'unapplied', description: 'd' }
        : { id: args.job_id, title: 'Dataanalytiker', company: 'Acme', status: 'unapplied', description: 'd' }

    async function importOne() {
      await screen.findAllByRole('listitem')
      await userEvent.click(screen.getByRole('button', { name: 'Add a job' }))
      await userEvent.type(screen.getByLabelText('Link'), 'https://example.com/1')
      await userEvent.click(screen.getByRole('button', { name: 'Import' }))
      await userEvent.click(await screen.findByRole('button', { name: 'Open' }))
    }

    it('has a secondary Add a job button that opens the dialog', async () => {
      stubNarrow(false)
      setup()
      render(<Matches />)
      await screen.findAllByRole('listitem')
      const button = screen.getByRole('button', { name: 'Add a job' })
      expect(button).toHaveClass('secondary')
      await userEvent.click(button)
      expect(screen.getByRole('dialog', { name: 'Add a job' })).toBeInTheDocument()
    })

    it('Open shows the imported posting full width', async () => {
      stubNarrow(false)
      const { call } = setup({ import_posting: imported, show: showImported })
      render(<Matches />)
      await importOne()
      expect(await screen.findByRole('heading', { name: 'Imported Role', level: 2 })).toBeInTheDocument()
      expect(call).toHaveBeenCalledWith('show', { job_id: 'manual.zz' })
      await userEvent.click(screen.getByRole('button', { name: '← Matches' }))
      await screen.findAllByRole('listitem')
      // back in the list, the imported ad is not a row; it was open until the user left it
      expect(screen.queryByRole('heading', { name: 'Imported Role', level: 2 })).toBeNull()
    })

    it('stays open through a refresh though the list does not hold it, with no previous and next', async () => {
      stubNarrow(false)
      const { call } = setup({ import_posting: imported, show: showImported })
      render(<Matches />)
      await importOne()
      await screen.findByRole('heading', { name: 'Imported Role', level: 2 })
      await waitFor(() => expect(call).toHaveBeenCalledWith('list_matches', {}))
      await new Promise((r) => setTimeout(r, 20))
      expect(screen.getByRole('heading', { name: 'Imported Role', level: 2 })).toBeInTheDocument()
      expect(screen.queryByRole('group', { name: 'Previous and next match' })).toBeNull()
    })
  })

  it('opens on the list alone, nothing selected', async () => {
    const { call } = setup()
    render(<Matches />)
    const rows = await screen.findAllByRole('listitem')
    expect(call).not.toHaveBeenCalledWith('show', expect.anything())
    for (const row of rows) expect(within(row).getByRole('button')).not.toHaveAttribute('aria-current', 'true')
  })

  it('back in the list, marks the row last read, with no dash', async () => {
    setup()
    render(<Matches />)
    await userEvent.click(within((await screen.findAllByRole('listitem'))[1]).getByRole('button'))
    await userEvent.click(await screen.findByRole('button', { name: '← Matches' }))
    const rows = await screen.findAllByRole('listitem')
    expect(within(rows[1]).getByRole('button')).toHaveAttribute('aria-current', 'true')
    expect(within(rows[0]).getByRole('button')).not.toHaveAttribute('aria-current', 'true')
    expect(rows[1].querySelector('.dash-s')).toBeNull()
  })

  describe('an open posting', () => {
    const three = [
      match({ id: 'jobindex.1', title: 'First job' }),
      match({ id: 'jobindex.2', title: 'Second job' }),
      match({ id: 'jobindex.3', title: 'Third job' }),
    ]
    const stepping = () => setup({ show: (a: Record<string, unknown>) => ({ ...three.find((r) => r.id === a.job_id), description: 'd', url: '' }) }, three)

    it('takes the whole screen at any width, the list steps aside until ← Matches', async () => {
      stubNarrow(false)
      const onPushed = vi.fn()
      stepping()
      render(<Matches onPushed={onPushed} />)
      await userEvent.click(await screen.findByRole('button', { name: /Second job/ }))
      expect(await screen.findByRole('heading', { name: 'Second job', level: 2 })).toBeInTheDocument()
      expect(screen.queryByRole('heading', { name: 'Matches', level: 1 })).toBeNull()
      expect(screen.queryByRole('listitem')).toBeNull()
      // a wide window keeps its sidebar
      expect(onPushed).toHaveBeenLastCalledWith(false)
      await userEvent.click(screen.getByRole('button', { name: '← Matches' }))
      expect(await screen.findAllByRole('listitem')).toHaveLength(3)
      delete (window as { matchMedia?: unknown }).matchMedia
    })

    it('says where it is in the list and steps to the previous and next match', async () => {
      stepping()
      render(<Matches />)
      await userEvent.click(await screen.findByRole('button', { name: /Second job/ }))
      const stepper = await screen.findByRole('group', { name: 'Previous and next match' })
      expect(stepper).toHaveTextContent('2 of 3')
      await userEvent.click(within(stepper).getByRole('button', { name: 'Next match' }))
      expect(await screen.findByRole('heading', { name: 'Third job', level: 2 })).toBeInTheDocument()
      expect(screen.getByRole('group', { name: 'Previous and next match' })).toHaveTextContent('3 of 3')
      expect(screen.getByRole('button', { name: 'Next match' })).toBeDisabled()
      await userEvent.click(screen.getByRole('button', { name: 'Previous match' }))
      await userEvent.click(screen.getByRole('button', { name: 'Previous match' }))
      expect(await screen.findByRole('heading', { name: 'First job', level: 2 })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Previous match' })).toBeDisabled()
    })

    it('j and k step, Esc goes back to the list', async () => {
      stepping()
      render(<Matches />)
      await userEvent.click(await screen.findByRole('button', { name: /First job/ }))
      await screen.findByRole('heading', { name: 'First job', level: 2 })
      await userEvent.keyboard('j')
      expect(await screen.findByRole('heading', { name: 'Second job', level: 2 })).toBeInTheDocument()
      await userEvent.keyboard('k')
      expect(await screen.findByRole('heading', { name: 'First job', level: 2 })).toBeInTheDocument()
      await userEvent.keyboard('{Escape}')
      expect(await screen.findAllByRole('listitem')).toHaveLength(3)
    })

    it('j on a dialog’s button leaves the posting behind it alone', async () => {
      stepping()
      render(<Matches />)
      await userEvent.click(await screen.findByRole('button', { name: /First job/ }))
      await userEvent.click(await screen.findByRole('button', { name: 'Status' }))
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }).focus()
      await userEvent.keyboard('j')
      expect(screen.getByRole('dialog')).toBeInTheDocument()
      expect(screen.getByRole('heading', { name: 'First job', level: 2 })).toBeInTheDocument()
    })

    it('Esc on the score’s hint closes the hint and stays on the posting', async () => {
      setup({ show: { id: 'jobindex.1', title: 'Dataanalytiker', company: 'Acme', status: 'unapplied', score: 0.9, score_reason: 'Fits well' } })
      render(<Matches />)
      await userEvent.click(within((await screen.findAllByRole('listitem'))[0]).getByRole('button'))
      screen.getByRole('button', { name: 'Why this score' }).focus()
      await screen.findByRole('tooltip')
      await userEvent.keyboard('{Escape}')
      expect(screen.queryByRole('tooltip')).toBeNull()
      expect(screen.getByRole('heading', { name: 'Dataanalytiker', level: 2 })).toBeInTheDocument()
    })

    it('j with Cmd, Ctrl or Alt held does not step', async () => {
      stepping()
      render(<Matches />)
      await userEvent.click(await screen.findByRole('button', { name: /First job/ }))
      await screen.findByRole('heading', { name: 'First job', level: 2 })
      await userEvent.keyboard('{Meta>}j{/Meta}{Control>}j{/Control}{Alt>}j{/Alt}')
      expect(screen.getByRole('heading', { name: 'First job', level: 2 })).toBeInTheDocument()
    })

    it('the keys do nothing while a dialog is open', async () => {
      stepping()
      render(<Matches />)
      await userEvent.click(await screen.findByRole('button', { name: /First job/ }))
      await userEvent.click(await screen.findByRole('button', { name: 'Not for me' }))
      await userEvent.type(screen.getByLabelText('Why not?'), 'jk')
      expect(screen.getByRole('heading', { name: 'First job', level: 2 })).toBeInTheDocument()
      expect(screen.getByLabelText('Why not?')).toHaveValue('jk')
    })
  })

  it('keeps the score in the list score style', async () => {
    setup()
    render(<Matches />)
    const rows = await screen.findAllByRole('listitem')
    expect(within(rows[0]).getByText('0.91')).toHaveClass('score-s')
  })

  describe('in a narrow window', () => {
    afterEach(() => {
      delete (window as { matchMedia?: unknown }).matchMedia
    })

    it('shows the list alone, without opening the first posting', async () => {
      stubNarrow(true)
      const { call } = setup()
      render(<Matches />)
      expect(await screen.findAllByRole('listitem')).toHaveLength(2)
      expect(call).not.toHaveBeenCalledWith('show', expect.anything())
      expect(screen.queryByRole('button', { name: '← Matches' })).toBeNull()
      // Nothing is open, so no row reads as selected.
      for (const row of screen.getAllByRole('listitem')) expect(within(row).getByRole('button')).not.toHaveAttribute('aria-current', 'true')
    })

    it('pushes the posting alone on select, and the back link returns to the list', async () => {
      stubNarrow(true)
      const onPushed = vi.fn()
      setup()
      render(<Matches onPushed={onPushed} />)
      await userEvent.click(within((await screen.findAllByRole('listitem'))[0]).getByRole('button'))
      expect(await screen.findByRole('heading', { name: 'Dataanalytiker', level: 2 })).toBeInTheDocument()
      expect(screen.queryByRole('listitem')).toBeNull()
      expect(onPushed).toHaveBeenLastCalledWith(true)
      await userEvent.click(screen.getByRole('button', { name: '← Matches' }))
      expect(await screen.findAllByRole('listitem')).toHaveLength(2)
      expect(onPushed).toHaveBeenLastCalledWith(false)
    })

  })

  describe('the prepared application', () => {
    afterEach(() => {
      delete (window as { matchMedia?: unknown }).matchMedia
    })
    const materials = {
      output_dir: '/abs/jobs/output/jobindex.1',
      pdfs: { cv: '/abs/jobs/output/jobindex.1/cv.pdf', cover_letter: '/abs/jobs/output/jobindex.1/cover_letter.pdf' },
      pngs: { cv: ['/abs/jobs/output/jobindex.1/cv_page_1.png'], cover_letter: ['/abs/jobs/output/jobindex.1/cover_letter_page_1.png'] },
      keywords: [],
      tailoring: [],
      page_counts: { cv: 1, cover_letter: 1 },
      cover_letter_words: 300,
      rendered: false,
    }
    const prepared = () =>
      setup({
        show: { id: 'jobindex.1', title: 'Dataanalytiker', title_en: 'Data Analyst', company: 'Acme', location: 'Copenhagen', status: 'prepared', materials },
        set_status: { job_id: 'jobindex.1', status: 'applied', current: 'applied' },
      })

    it('wide: See the application takes the whole screen, ← Posting brings the posting back, ← Matches the list with its row marked', async () => {
      stubNarrow(false)
      prepared()
      render(<Matches />)
      await userEvent.click(within((await screen.findAllByRole('listitem'))[0]).getByRole('button'))
      await userEvent.click(await screen.findByRole('button', { name: 'See the application' }))
      expect(await screen.findByRole('heading', { name: 'Ready to send' })).toBeInTheDocument()
      expect(screen.queryByRole('heading', { name: 'Dataanalytiker', level: 2 })).toBeNull()
      // Two pages and the Revise column need the room the mockup gives them.
      expect(screen.queryByRole('heading', { name: 'Matches', level: 1 })).toBeNull()
      expect(screen.queryAllByRole('listitem').filter((li) => li.closest('.rows'))).toHaveLength(0)
      await userEvent.click(screen.getByRole('button', { name: '← Posting' }))
      expect(await screen.findByRole('heading', { name: 'Dataanalytiker', level: 2 })).toBeInTheDocument()
      await userEvent.click(screen.getByRole('button', { name: '← Matches' }))
      expect(within((await screen.findAllByRole('listitem'))[0]).getByRole('button')).toHaveAttribute('aria-current', 'true')
    })

    it('keeps the job open when the list no longer holds it', async () => {
      stubNarrow(false)
      let rows = two
      setup({
        list_matches: () => matchesResult(rows),
        show: (a: Record<string, unknown>) => ({ id: a.job_id, title: 'Dataanalytiker', company: 'Acme', status: 'prepared', materials }),
      })
      render(<Matches />)
      await userEvent.click(within((await screen.findAllByRole('listitem'))[0]).getByRole('button'))
      await userEvent.click(await screen.findByRole('button', { name: 'See the application' }))
      rows = [two[1]]
      await userEvent.click(screen.getByRole('button', { name: '← Posting' }))
      await userEvent.click(await screen.findByRole('button', { name: 'See the application' }))
      expect(await screen.findByRole('heading', { name: 'Ready to send' })).toBeInTheDocument()
    })

    it('narrow: a second pushed screen with ← Posting, and back to the posting then the list', async () => {
      stubNarrow(true)
      const onPushed = vi.fn()
      prepared()
      render(<Matches onPushed={onPushed} />)
      await userEvent.click(within((await screen.findAllByRole('listitem'))[0]).getByRole('button'))
      await userEvent.click(await screen.findByRole('button', { name: 'See the application' }))
      expect(await screen.findByRole('heading', { name: 'Ready to send' })).toBeInTheDocument()
      expect(onPushed).toHaveBeenLastCalledWith(true)
      expect(screen.queryByRole('button', { name: '← Matches' })).toBeNull()
      await userEvent.click(screen.getByRole('button', { name: '← Posting' }))
      expect(await screen.findByRole('heading', { name: 'Dataanalytiker', level: 2 })).toBeInTheDocument()
      await userEvent.click(screen.getByRole('button', { name: '← Matches' }))
      expect(await screen.findAllByRole('listitem')).toHaveLength(2)
    })

    it("after I've applied, shows the notice and returns to the list", async () => {
      stubNarrow(true)
      const { call } = prepared()
      render(<Matches />)
      await userEvent.click(within((await screen.findAllByRole('listitem'))[0]).getByRole('button'))
      await userEvent.click(await screen.findByRole('button', { name: 'See the application' }))
      const applied = await screen.findByRole('button', { name: "I've applied" })
      call.mockClear()
      await userEvent.click(applied)
      expect(await screen.findByText(/Applied: Data Analyst\. It is in Applications now\./)).toBeInTheDocument()
      expect(await screen.findAllByRole('listitem')).toHaveLength(2)
      expect(call).toHaveBeenCalledWith('list_matches', {})
    })
  })
})

describe('Matches, weak matches before a first real one (issue 643)', () => {
  const weakRows = [
    match({ id: 'jobindex.7', title: 'Maybe Analyst', score: 0.4 }),
    match({ id: 'jobindex.8', title: 'Maybe Engineer', company: 'Globex', score: 0.3 }),
  ]
  const sourcesHint = { matches: weakRows, hint: 'sources', sources: [{ key: 'linkedin_discovery', label: 'LinkedIn' }, { key: 'hellowork_discovery', label: 'HelloWork' }] }
  const keywordsHint = { matches: weakRows, hint: 'keywords', sources: [] }

  it('shows the weak ones as marked rows under a line naming the sources that are off', async () => {
    setup({}, [], { scored: 5, weak: sourcesHint })
    render(<Matches onChooseDiscovery={() => {}} />)
    expect(await screen.findByText(/2 weak matches found\./)).toHaveTextContent(
      /can also find employers on LinkedIn and HelloWork, at your own risk: read the legal disclaimer\. Turn it on in Settings/,
    )
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getAllByText('Weak match')).toHaveLength(2)
    expect(screen.queryByText(/Nothing has reached your bar/)).toBeNull()
  })

  it('"Turn it on in Settings" goes to the employers', async () => {
    setup({}, [], { scored: 5, weak: sourcesHint })
    const onChooseDiscovery = vi.fn()
    render(<Matches onChooseDiscovery={onChooseDiscovery} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Turn it on in Settings' }))
    expect(onChooseDiscovery).toHaveBeenCalledTimes(1)
  })

  it('with every source on, says to broaden the keywords, linked to the search', async () => {
    setup({}, [], { scored: 5, weak: keywordsHint })
    const onCheckSearch = vi.fn()
    render(<Matches onCheckSearch={onCheckSearch} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Broaden your search keywords to find closer ones.' }))
    expect(onCheckSearch).toHaveBeenCalledTimes(1)
  })

  it('says "1 weak match found" for one', async () => {
    setup({}, [], { scored: 5, weak: { ...keywordsHint, matches: weakRows.slice(0, 1) } })
    render(<Matches />)
    expect(await screen.findByText(/1 weak match found\./)).toBeInTheDocument()
  })

  it('a weak row opens its posting like any match', async () => {
    setup({}, [], { scored: 5, weak: keywordsHint })
    render(<Matches />)
    await userEvent.click(within((await screen.findAllByRole('listitem'))[0]).getByRole('button'))
    expect(await screen.findByRole('button', { name: '← Matches' })).toBeInTheDocument()
  })

  it('on the phone (no callbacks) the line is plain text and the rows stay', async () => {
    setup({}, [], { scored: 5, weak: sourcesHint })
    render(<Matches />)
    expect(await screen.findByText(/2 weak matches found\./)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Turn it on in Settings' })).toBeNull()
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('keeps Lower the bar', async () => {
    setup({}, [], { scored: 5, weak: keywordsHint })
    render(<Matches onLowerBar={() => {}} />)
    expect(await screen.findByRole('button', { name: 'Lower the bar' })).toBeInTheDocument()
  })

  it('without weak matches the empty state is the old one', async () => {
    setup({}, [], { scored: 5, weak: null })
    render(<Matches />)
    expect(await screen.findByText('Nothing has reached your bar (65%) yet.')).toBeInTheDocument()
  })

  it('New only after a review shows no weak block', async () => {
    setup({}, [], { scored: 5, weak: keywordsHint, last_reviewed_at: '2026-10-29T08:00:00+00:00' })
    render(<Matches newOnlyFirst />)
    expect(await screen.findByText('Nothing new since your last review.')).toBeInTheDocument()
    expect(screen.queryByText(/weak match/)).toBeNull()
  })
})
