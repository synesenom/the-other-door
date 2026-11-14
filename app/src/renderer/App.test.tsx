// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { act } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { stubNarrow } from './testing'
import { match, mockDoor, matchesResult, summary } from './testing'
import { cvState, doctorReport, existingProfile, freshProfile } from './screens/onboarding/testing'

afterEach(cleanup)

function setup() {
  return mockDoor({ status_summary: summary(), list_matches: matchesResult([]) })
}

describe('App', () => {
  it('shows the splash while the server starts, then the app', async () => {
    let answer: (p: unknown) => void = () => undefined
    mockDoor({ status_summary: summary(), list_matches: matchesResult([]), show_profile: () => new Promise((r) => (answer = r)) })
    render(<App />)
    expect(await screen.findByRole('status', { name: 'Starting The other door' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).toBeNull()
    await act(async () => answer(existingProfile))
    expect(await screen.findByRole('navigation')).toBeInTheDocument()
    expect(screen.queryByRole('status', { name: 'Starting The other door' })).toBeNull()
  })

  it('has the five destinations in the sidebar', async () => {
    setup()
    render(<App />)
    const nav = await screen.findByRole('navigation')
    const names = within(nav).getAllByRole('button').map((b) => b.textContent)
    expect(names).toEqual(['Matches', 'Applications', 'Profile', 'Settings', 'Analytics'])
  })

  it('each destination opens its screen, and the app opens on Matches', async () => {
    setup()
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Matches' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Applications' }))
    expect(await screen.findByRole('heading', { name: 'Applications', level: 1 })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Matches' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    expect(await screen.findByRole('region', { name: 'Connections' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Profile' }))
    expect(await screen.findByRole('heading', { name: 'Profile', level: 1 })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Analytics' }))
    expect(await screen.findByRole('region', { name: 'Claude usage' })).toBeInTheDocument()
  })

  it('opens every screen at its top, wherever the last one was scrolled to', async () => {
    setup()
    const tops: number[] = []
    const was = HTMLElement.prototype.scrollTo
    HTMLElement.prototype.scrollTo = function (this: HTMLElement, o?: ScrollToOptions | number) {
      if (this.classList.contains('main') && typeof o === 'object') tops.push(o.top ?? -1)
    } as typeof HTMLElement.prototype.scrollTo
    try {
      render(<App />)
      await screen.findByRole('heading', { name: 'Matches' })
      tops.length = 0
      await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
      await screen.findByRole('region', { name: 'Connections' })
      expect(tops).toContain(0)
    } finally {
      HTMLElement.prototype.scrollTo = was
    }
  })

  it('marks the current destination', async () => {
    setup()
    render(<App />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Matches' })).toHaveAttribute('aria-current', 'page'))
    expect(screen.getByRole('button', { name: 'Applications' })).not.toHaveAttribute('aria-current')
  })

  it('names the last run at the foot when the summary has one', async () => {
    mockDoor({
      status_summary: summary({
        since_last_review: { last_reviewed_at: null, runs: 1, last_run: { finished_at: '2026-10-28T09:30:00' }, new_matches: 0, site_failures: [] },
      }),
      list_matches: matchesResult([]),
    })
    const { container } = render(<App />)
    await waitFor(() => expect(container.querySelector('.sidebar-foot .small.muted')).toHaveTextContent(/^Last run /), { timeout: 5000 }) // a slow Windows runner missed the 1 s default
  })

  it('has no last-run caption when there was no run', async () => {
    setup()
    render(<App />)
    await screen.findByRole('heading', { name: 'Matches' })
    expect(screen.queryByText(/^Last run/)).toBeNull()
  })

  describe('in a narrow window', () => {
    afterEach(() => {
      delete (window as { matchMedia?: unknown }).matchMedia
    })

    it('shows the same five destinations as a tab bar, the current one marked with a dash', async () => {
      stubNarrow(true)
      setup()
      const { container } = render(<App />)
      const nav = await screen.findByRole('navigation')
      expect(within(nav).getAllByRole('button').map((b) => b.textContent)).toEqual(['Matches', 'Applications', 'Profile', 'Settings', 'Analytics'])
      const current = within(nav).getByRole('button', { name: 'Matches' })
      await waitFor(() => expect(current).toHaveAttribute('aria-current', 'page'))
      expect(current.querySelector('.tab-dash')).not.toBeNull()
      expect(container.querySelectorAll('.tab-dash')).toHaveLength(1)
    })

    it('each tab has an icon', async () => {
      stubNarrow(true)
      setup()
      render(<App />)
      const nav = await screen.findByRole('navigation')
      for (const b of within(nav).getAllByRole('button')) expect(b.querySelector('svg[aria-hidden="true"]')).not.toBeNull()
    })

    it('has no tab dash in a wide window', () => {
      stubNarrow(false)
      setup()
      const { container } = render(<App />)
      expect(container.querySelector('.tab-dash')).toBeNull()
    })

    it('hides the tab bar while a posting is pushed and brings it back with the back link', async () => {
      stubNarrow(true)
      mockDoor({
        status_summary: summary(),
        list_matches: matchesResult([match({ id: 'jobindex.1', title: 'Dataanalytiker' })]),
        show: { id: 'jobindex.1', title: 'Dataanalytiker', company: 'Acme', status: 'unapplied' },
      })
      render(<App />)
      await userEvent.click(await screen.findByRole('button', { name: /Dataanalytiker/ }))
      expect(await screen.findByRole('heading', { name: 'Dataanalytiker' })).toBeInTheDocument()
      expect(screen.queryByRole('navigation')).toBeNull()
      await userEvent.click(screen.getByRole('button', { name: '← Matches' }))
      expect(screen.getByRole('navigation')).toBeInTheDocument()
    })

    it('keeps the tab bar hidden on Ready to send and brings it back at the list', async () => {
      stubNarrow(true)
      mockDoor({
        status_summary: summary(),
        list_matches: matchesResult([match({ id: 'jobindex.1', title: 'Dataanalytiker' })]),
        show: {
          id: 'jobindex.1', title: 'Dataanalytiker', company: 'Acme', status: 'prepared',
          materials: { output_dir: '/abs/jobs/output/jobindex.1', pdfs: {}, pngs: { cv: [], cover_letter: [] }, keywords: [], tailoring: [], page_counts: { cv: 1, cover_letter: 1 }, cover_letter_words: 300, rendered: false },
        },
      })
      render(<App />)
      await userEvent.click(await screen.findByRole('button', { name: /Dataanalytiker/ }))
      await userEvent.click(await screen.findByRole('button', { name: 'See the application' }))
      expect(await screen.findByRole('heading', { name: 'Ready to send' })).toBeInTheDocument()
      expect(screen.queryByRole('navigation')).toBeNull()
      await userEvent.click(screen.getByRole('button', { name: '← Posting' }))
      expect(screen.queryByRole('navigation')).toBeNull()
      await userEvent.click(await screen.findByRole('button', { name: '← Matches' }))
      expect(screen.getByRole('navigation')).toBeInTheDocument()
    })

    it('hides the tab bar while an application is pushed', async () => {
      stubNarrow(true)
      mockDoor({
        status_summary: summary(),
        list_matches: (a: Record<string, unknown>) =>
          matchesResult(a['closed'] ? [] : [match({ id: 'jobindex.2', title: 'Applied job', status: 'applied' })]),
        show: { id: 'jobindex.2', title: 'Applied job', company: 'Acme', status: 'applied' },
      })
      render(<App />)
      await userEvent.click(await screen.findByRole('button', { name: 'Applications' }))
      await userEvent.click(await screen.findByRole('button', { name: /Applied job/ }))
      expect(await screen.findByRole('button', { name: '← Applications' })).toBeInTheDocument()
      expect(screen.queryByRole('navigation')).toBeNull()
    })
  })

  it('asks for the summary once at startup, for the caption and Matches together', async () => {
    const { call } = setup()
    render(<App />)
    expect(await screen.findByText(/Nothing scored yet/)).toBeInTheDocument()
    expect(call.mock.calls.filter((c) => c[0] === 'status_summary')).toHaveLength(1)
  })

  it('says so in a banner and the window title when it runs on the demo data', async () => {
    const { info } = setup()
    info.mockResolvedValue({ demo: true })
    render(<App />)
    const tag = await screen.findByRole('note', { name: 'Demo data' })
    expect(tag).toHaveTextContent('Demo')
    expect(tag).toHaveAttribute('title', expect.stringContaining('Made-up jobs'))
    await waitFor(() => expect(document.title).toBe('The other door (demo)'))
  })

  it('shows no banner on your own data', async () => {
    setup()
    render(<App />)
    await screen.findByText(/Nothing scored yet/)
    expect(screen.queryByRole('note', { name: 'Demo data' })).toBeNull()
  })
})

const RECORD = {
  started_at: '2026-10-29T08:02:00+00:00',
  finished_at: '2026-10-29T08:21:00+00:00',
  elapsed_s: 60,
  steps: [],
  skipped: {},
  search: null,
  collect: null,
  match: { failed: [] },
  new_above_threshold: ['a.1', 'a.2'],
  top: [{ id: 'a.1', score: 0.86, title: 'Finance Controller', company: 'Tyrell Maritime' }],
  failures: [],
}
const sidebarButton = () => within(screen.getByRole('complementary')).getByRole('button', { name: /Find(ing)? (new )?jobs/ })

function runSetup(findJobs: (args: Record<string, unknown>) => unknown = () => RECORD) {
  const h = mockDoor({ status_summary: summary(), list_matches: matchesResult([match()]), find_jobs: findJobs })
  return h
}

describe('App, Find new jobs', () => {
  it('starts a run from the sidebar and shows the Finding jobs screen in place of the page', async () => {
    let finish!: () => void
    const h = runSetup(() => new Promise((r) => (finish = () => r(RECORD))))
    render(<App />)
    await screen.findByRole('heading', { name: 'Matches' })
    expect(sidebarButton()).toBeEnabled()
    await userEvent.click(sidebarButton())
    expect(await screen.findByRole('heading', { name: 'Finding jobs', level: 1 })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Matches' })).toBeNull()
    expect(h.call.mock.calls.filter((c) => c[0] === 'find_jobs')).toHaveLength(1)
    expect(sidebarButton()).toHaveTextContent('Finding jobs…')
    expect(sidebarButton()).toBeDisabled() // already on the run's screen: nothing to click
    finish()
    expect(await screen.findByRole('heading', { level: 2, name: /2 new matches/ })).toBeInTheDocument()
  })

  it('a plan that is nearly full after the run is said once the summary is read again', async () => {
    let ran = false
    const low = { as_of: new Date().toISOString(), status: 'allowed', five_hour: { used: 0.9 }, room: { find: 1, prepare: 2 }, binding: 'five_hour' }
    mockDoor({ status_summary: () => summary(ran ? { plan: low } : {}), list_matches: matchesResult([match()]), find_jobs: () => ((ran = true), RECORD) })
    render(<App />)
    await screen.findByRole('heading', { name: 'Matches' })
    expect(screen.queryByText(/more applications this window/)).toBeNull()
    await userEvent.click(sidebarButton())
    await userEvent.click(await screen.findByRole('button', { name: 'View matches' }))
    expect(await screen.findByText('Room for about 2 more applications this window')).toBeInTheDocument()
  })

  it('the run goes on while you look at another screen, and the button returns to it', async () => {
    let finish!: () => void
    const h = runSetup(() => new Promise((r) => (finish = () => r(RECORD))))
    render(<App />)
    await screen.findByRole('heading', { name: 'Matches' })
    await userEvent.click(sidebarButton())
    await screen.findByRole('heading', { name: 'Finding jobs', level: 1 })
    await userEvent.click(screen.getByRole('button', { name: 'Applications' }))
    expect(screen.queryByRole('heading', { name: 'Finding jobs' })).toBeNull()
    expect(sidebarButton()).toHaveTextContent('Finding jobs…')
    expect(sidebarButton()).toBeEnabled() // from another screen it leads back to the run
    await userEvent.click(sidebarButton())
    expect(await screen.findByRole('heading', { name: 'Finding jobs', level: 1 })).toBeInTheDocument()
    expect(h.call.mock.calls.filter((c) => c[0] === 'find_jobs')).toHaveLength(1)
    await act(async () => finish())
  })

  it('shows the live board the main process pushes', async () => {
    let finish!: () => void
    const h = runSetup(() => new Promise((r) => (finish = () => r(RECORD))))
    render(<App />)
    await screen.findByRole('heading', { name: 'Matches' })
    await userEvent.click(sidebarButton())
    await screen.findByRole('heading', { name: 'Finding jobs', level: 1 })
    act(() =>
      h.pushBoard({
        active: true, own: true, started_at: RECORD.started_at, purpose: 'run', message: 'm',
        steps: [{ name: 'search', status: 'done', detail: '9 postings from 2 boards' }],
      }),
    )
    expect(await screen.findByText('9 postings from 2 boards')).toBeInTheDocument()
    await act(async () => finish())
  })

  it('a notification clicked after View matches still opens the run it is about', async () => {
    const h = runSetup()
    render(<App />)
    await screen.findByRole('heading', { name: 'Matches' })
    await userEvent.click(sidebarButton())
    await userEvent.click(await screen.findByRole('button', { name: 'View matches' }))
    await screen.findByRole('heading', { name: 'Matches' })
    act(() => h.pushOpen({ screen: 'finding' }))
    expect(await screen.findByRole('heading', { level: 2, name: /2 new matches/ })).toBeInTheDocument()
    expect(within(screen.getByRole('main')).queryByRole('button', { name: 'Find new jobs' })).toBeNull()
  })

  it('after the run the table and the last-run caption are fetched again, and View matches shows the new ones', async () => {
    const h = runSetup()
    render(<App />)
    await screen.findByRole('heading', { name: 'Matches' })
    const before = h.call.mock.calls.filter((c) => c[0] === 'status_summary').length
    const listBefore = h.call.mock.calls.filter((c) => c[0] === 'list_matches').length
    await userEvent.click(sidebarButton())
    await userEvent.click(await screen.findByRole('button', { name: 'View matches' }))
    expect(await screen.findByRole('heading', { name: 'Matches' })).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'New only' })).toHaveAttribute('aria-checked', 'true')
    expect(h.call.mock.calls.filter((c) => c[0] === 'status_summary').length).toBeGreaterThan(before)
    const lists = h.call.mock.calls.filter((c) => c[0] === 'list_matches')
    expect(lists.length).toBeGreaterThan(listBefore)
  })

  it('a Stop goes back to the screen the run was started from', async () => {
    const h = runSetup(() => new Promise(() => {}))
    h.call.mockImplementation(async (tool: string) => {
      if (tool === 'find_jobs') {
        await new Promise((r) => setTimeout(r, 20))
        return { ok: false, error: 'stopped', stopped: true } as never
      }
      return { ok: true, data: tool === 'status_summary' ? summary() : matchesResult([]) } as never
    })
    render(<App />)
    await screen.findByRole('heading', { name: 'Matches' })
    await userEvent.click(screen.getByRole('button', { name: 'Applications' }))
    await userEvent.click(sidebarButton())
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Finding jobs' })).toBeNull())
    expect(screen.getByRole('button', { name: 'Applications' })).toHaveAttribute('aria-current', 'page')
  })

  it('a run started elsewhere shows read-only, and the button cannot start another', async () => {
    const h = runSetup()
    render(<App />)
    await screen.findByRole('heading', { name: 'Matches' })
    act(() =>
      h.pushBoard({ active: true, own: false, started_at: RECORD.started_at, purpose: 'run', message: 'm', steps: [{ name: 'search', status: 'running', detail: '' }] }),
    )
    expect(await screen.findByText(/A run started elsewhere is in progress/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull()
    expect(sidebarButton()).toBeDisabled()
    expect(h.call.mock.calls.some((c) => c[0] === 'find_jobs')).toBe(false)
    act(() => h.pushBoard({ active: false }))
    expect(await screen.findByRole('heading', { name: 'Matches' })).toBeInTheDocument()
    expect(sidebarButton()).toBeEnabled()
  })

  it('a run already going when the window opens is shown', async () => {
    const h = runSetup()
    await h.runBoard.mockResolvedValue({ active: true, own: false, started_at: RECORD.started_at, purpose: 'run', message: 'm', steps: [] } as never)
    render(<App />)
    expect(await screen.findByText(/A run started elsewhere is in progress/)).toBeInTheDocument()
  })

  it('a narrow window, with no sidebar foot, has a Find new jobs pill in the Matches header that starts the same run', async () => {
    stubNarrow(true)
    const h = runSetup()
    render(<App />)
    const main = await screen.findByRole('main')
    await userEvent.click(await within(main).findByRole('button', { name: 'Find new jobs' }))
    expect(await screen.findByRole('heading', { level: 2, name: /2 new matches/ })).toBeInTheDocument()
    expect(h.call.mock.calls.some((c) => c[0] === 'find_jobs')).toBe(true)
    delete (window as { matchMedia?: unknown }).matchMedia
  })

  it('a run started elsewhere a moment before the click is shown read only', async () => {
    const h = runSetup(() => {
      throw { message: 'a run is in progress (started 06:30, pid 4242); try again when it has finished' }
    })
    render(<App />)
    await screen.findByRole('heading', { name: 'Matches' })
    h.runBoard.mockResolvedValue({ active: true, own: false, started_at: RECORD.started_at, purpose: 'run', message: 'm', steps: [] } as never)
    await userEvent.click(sidebarButton())
    expect(await screen.findByText(/A run started elsewhere is in progress/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  describe('a clicked notification (door:open)', () => {
    const dir = '/abs/jobs/output/jobindex.1'
    const materials = {
      output_dir: dir,
      pdfs: { cv: `${dir}/cv.pdf`, cover_letter: `${dir}/cover_letter.pdf` },
      pngs: { cv: [`${dir}/cv_page_1.png`], cover_letter: [`${dir}/cover_letter_page_1.png`] },
      keywords: [],
      tailoring: [],
      page_counts: { cv: 1, cover_letter: 1 },
      cover_letter_words: 300,
      rendered: false,
    }
    const posting = (over: Record<string, unknown> = {}) => ({ id: 'jobindex.1', title: 'Data Analyst', company: 'Acme', location: 'Copenhagen', description: 'text', status: 'unapplied', materials: null, ...over })
    const open = (over: Record<string, unknown> = {}) => mockDoor({ status_summary: summary(), list_matches: matchesResult([match()]), show: posting(), ...over })

    it('matches with New only turns the switch on', async () => {
      const { pushOpen } = open()
      render(<App />)
      await screen.findByRole('heading', { name: 'Matches' })
      act(() => pushOpen({ screen: 'matches', newOnly: true }))
      await waitFor(() => expect(screen.getByRole('switch', { name: 'New only' })).toHaveAttribute('aria-checked', 'true'))
    })

    it('finding with no run of this window to show stays where it is', async () => {
      const { pushOpen } = open()
      render(<App />)
      await screen.findByRole('heading', { name: 'Matches' })
      act(() => pushOpen({ screen: 'finding' }))
      await act(() => new Promise((r) => setTimeout(r, 20)))
      expect(screen.getByRole('heading', { name: 'Matches' })).toBeInTheDocument()
      expect(screen.queryByRole('heading', { name: 'Finding jobs' })).toBeNull()
    })

    it('materials opens Ready to send on that document', async () => {
      const { pushOpen } = open({ show: posting({ status: 'unapplied', materials }) })
      render(<App />)
      await screen.findByRole('heading', { name: 'Matches' })
      act(() => pushOpen({ screen: 'materials', jobId: 'jobindex.1', inPlay: false, document: 'cv' }))
      expect(await screen.findByRole('heading', { name: 'Ready to send' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /^CV · / })).toHaveAttribute('aria-pressed', 'true')
    })

    it('materials for a job in play goes to Applications', async () => {
      const { pushOpen } = open({ list_matches: matchesResult([match({ status: 'prepared' })]), show: posting({ status: 'prepared', materials }) })
      render(<App />)
      await screen.findByRole('heading', { name: 'Matches' })
      act(() => pushOpen({ screen: 'materials', jobId: 'jobindex.1', inPlay: true }))
      expect(await screen.findByRole('heading', { name: 'Ready to send' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Applications' })).toHaveAttribute('aria-current', 'page')
    })

    it('posting opens that job even when the list does not hold it', async () => {
      const { pushOpen } = open({ list_matches: matchesResult([]) })
      render(<App />)
      await screen.findByRole('heading', { name: 'Matches' })
      act(() => pushOpen({ screen: 'posting', jobId: 'jobindex.1', inPlay: false }))
      expect(await screen.findByRole('heading', { name: 'Data Analyst' })).toBeInTheDocument()
    })

    it('ignores a target it does not know, and unsubscribes on unmount', async () => {
      const { pushOpen, openListeners } = open()
      const { unmount } = render(<App />)
      await screen.findByRole('heading', { name: 'Matches' })
      act(() => pushOpen({ screen: 'nowhere' }))
      act(() => pushOpen(null))
      expect(screen.getByRole('heading', { name: 'Matches' })).toBeInTheDocument()
      expect(openListeners.size).toBe(1) // subscribed
      unmount()
      expect(openListeners.size).toBe(0) // the unsubscribe from onOpen ran
    })
  })
})

// The first-launch gate (issue 221): show_profile decides between the wizard and the app.
describe('App, the first-launch gate', () => {
  const profile = (over: Record<string, unknown> = {}) => ({ ...existingProfile, ...over })
  const gated = (show: unknown, extra: Record<string, unknown> = {}) =>
    mockDoor({ show_profile: show, status_summary: summary(), list_matches: matchesResult([]), doctor: doctorReport('ok'), ...extra })

  it('a home without a config opens the wizard, with no sidebar', async () => {
    gated(freshProfile)
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Tell me about yourself' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).toBeNull()
    expect(screen.queryByRole('complementary')).toBeNull()
  })

  it('Save on a first launch goes straight to Finding jobs with a first run', async () => {
    const { call, pickCvFiles } = gated(freshProfile, {
      draft_cv: { markdown: '# Ada\n', provenance: [], todos: [], sources: [] },
      infer_basics: { name: 'Ada', email: 'ada@x.dk', location: 'Aarhus', languages: ['English'], remote: 'hybrid', missing: [] },
      suggest_titles: { titles: [{ title: 'Lead', reason: 'you led', recommended: true }] },
      keywords: { keywords: ['lead'], topic_terms: [] },
      init_profile: {}, save_cv: {}, find_jobs: () => new Promise(() => {}),
    })
    pickCvFiles.mockResolvedValue({ files: [{ token: 't', name: 'cv.pdf', size: 1 }], refused: [] })
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Drop relevant documents here (CV or LinkedIn PDF)' }))
    await screen.findByText('cv.pdf')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Save and start searching' }))
    await waitFor(() => expect(call).toHaveBeenCalledWith('find_jobs', { skip: ['discover', 'follow', 'collect'] }, expect.anything()))
    expect(await screen.findByRole('heading', { name: 'Finding jobs', level: 1 })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Tell me about yourself' })).toBeNull()
  })

  it('a first run with few matches reminds about the discovery sources left off; a later one does not', async () => {
    const saved = { ...existingProfile, config: { ...existingProfile.config!, linkedin_discovery: false, hellowork_discovery: false } }
    let reads = 0
    const { pickCvFiles } = gated(() => (reads++ === 0 ? freshProfile : saved), {
      draft_cv: { markdown: '# Ada\n', provenance: [], todos: [], sources: [] },
      infer_basics: { name: 'Ada', email: 'ada@x.dk', location: 'Aarhus', languages: ['English'], remote: 'hybrid', missing: [] },
      suggest_titles: { titles: [{ title: 'Lead', reason: 'you led', recommended: true }] },
      keywords: { keywords: ['lead'], topic_terms: [] },
      init_profile: {}, save_cv: {}, find_jobs: { ...RECORD, new_above_threshold: [], top: [] },
    })
    pickCvFiles.mockResolvedValue({ files: [{ token: 't', name: 'cv.pdf', size: 1 }], refused: [] })
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Drop relevant documents here (CV or LinkedIn PDF)' }))
    await screen.findByText('cv.pdf')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Save and start searching' }))
    const line = await screen.findByRole('note', { name: 'Employer discovery' })
    expect(line).toHaveTextContent(/LinkedIn and HelloWork/)
    await userEvent.click(within(line).getByRole('button', { name: 'Turn it on in Settings' }))
    expect(await screen.findByRole('heading', { name: 'Settings', level: 1 })).toBeInTheDocument()
    await userEvent.click(sidebarButton()) // the next run is not the first
    expect(await screen.findByRole('heading', { level: 2, name: 'No new matches' })).toBeInTheDocument()
    expect(screen.queryByRole('note', { name: 'Employer discovery' })).toBeNull()
  })

  it('a valid config opens Matches', async () => {
    gated(profile())
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Matches' })).toBeInTheDocument()
    expect(screen.getByRole('navigation')).toBeInTheDocument()
  })

  it('decides on show_profile alone: a doctor that never answers keeps nothing waiting', async () => {
    const { call } = gated(profile(), { doctor: () => new Promise(() => {}) })
    render(<App />)
    await screen.findByRole('heading', { name: 'Matches' })
    expect(call.mock.calls[0]![0]).toBe('show_profile')
    // doctor is asked once the shell is open, a moment after Matches shows
    await waitFor(() => expect(call.mock.calls.map((c) => c[0])).toContain('doctor'))
  })

  it('never shows the wizard in the demo, even if the profile has no config', async () => {
    const { info } = gated(freshProfile)
    info.mockResolvedValue({ demo: true })
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Matches' })).toBeInTheDocument()
  })

  it('on the phone: Matches, Applications and Settings; the profile is changed on the computer', async () => {
    const { info } = gated(profile())
    info.mockResolvedValue({ demo: false, remote: true })
    render(<App />)
    const nav = await screen.findByRole('navigation')
    expect(within(nav).getAllByRole('button').map((b) => b.textContent)).toEqual(['Matches', 'Applications', 'Settings'])
  })

  it('on the phone, doctor is never asked and what needs you is said, not a button to a screen it lacks', async () => {
    const { info, call } = gated(profile({ cv: cvState(), discovery_unchosen: [{ key: 'linkedin_discovery', label: 'LinkedIn' }] }))
    info.mockResolvedValue({ demo: false, remote: true })
    render(<App />)
    const foot = await screen.findByRole('group', { name: 'Needs you' })
    expect(within(foot).getByText('You have no CV yet')).toBeInTheDocument()
    expect(within(foot).queryByRole('button')).toBeNull()
    expect(within(foot).queryByText(/LinkedIn/)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await screen.findByRole('heading', { name: 'Settings', level: 1 })
    expect(call.mock.calls.map((c) => c[0])).not.toContain('doctor')
  })

  it('on the phone, a home with no profile says to set The other door up on the computer running The other door', async () => {
    const { info } = gated(freshProfile)
    info.mockResolvedValue({ demo: false, remote: true })
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Set up The other door first' })).toBeInTheDocument()
    expect(screen.getByText(/where it is installed/)).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).toBeNull()
  })

  it('does show it in the onboarding sandbox, whose folder is empty', async () => {
    const { info } = gated(freshProfile)
    info.mockResolvedValue({ demo: true, sandbox: 'onboard' })
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Tell me about yourself' })).toBeInTheDocument()
  })

  it('goes to the app when show_profile fails', async () => {
    gated(() => {
      throw new Error('server down')
    })
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Matches' })).toBeInTheDocument()
  })

  it('says in the sidebar and the title that it is the onboarding sandbox', async () => {
    const { info } = gated(profile())
    info.mockResolvedValue({ demo: true, sandbox: 'onboard' })
    render(<App />)
    expect(await screen.findByRole('note', { name: 'Onboarding sandbox' })).toHaveTextContent('Sandbox')
    await waitFor(() => expect(document.title).toBe('The other door (onboarding sandbox)'))
  })

  describe('the lines that need you, at the sidebar\'s foot', () => {
    const lines = () => within(screen.getByRole('complementary'))
    const sidebar = async () => within(await screen.findByRole('complementary'))

    it('a missing CV opens Profile on the CV', async () => {
      gated(profile({ cv: cvState() }))
      render(<App />)
      await screen.findByRole('heading', { name: 'Matches' })
      await userEvent.click(await lines().findByRole('button', { name: 'You have no CV yet' }))
      expect(await screen.findByLabelText('Your CV (Markdown)')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Profile' })).toHaveAttribute('aria-current', 'page')
    })

    it('the example CV has no line: a run refuses it and says why', async () => {
      gated(profile({ cv: cvState({ exists: true, is_example: true }) }))
      render(<App />)
      await screen.findByRole('heading', { name: 'Matches' })
      await act(() => new Promise((r) => setTimeout(r, 50))) // the profile has been read
      expect(lines().queryByRole('button', { name: /CV/ })).toBeNull()
    })

    it('Claude not signed in opens Settings', async () => {
      mockDoor({ show_profile: profile(), status_summary: summary(), list_matches: matchesResult([]), doctor: doctorReport('out') })
      render(<App />)
      await userEvent.click(await (await sidebar()).findByRole('button', { name: 'Claude is not signed in' }))
      expect(await screen.findByRole('region', { name: 'Connections' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Settings' })).toHaveAttribute('aria-current', 'page')
    })

    it('a failed Drive sync is said too', async () => {
      const drive = { connected: true, account: 'a@b.c', last_synced: null, last_error: 'offline', configured: true }
      mockDoor({ show_profile: profile(), status_summary: summary({ drive }), list_matches: matchesResult([]), doctor: doctorReport('ok') })
      render(<App />)
      expect(await (await sidebar()).findByRole('button', { name: 'Google Drive sync failed' })).toBeInTheDocument()
    })

    it('a connected Drive syncs once when the app opens; a pull reads the profile again', async () => {
      const drive = { connected: true, account: 'a@b.c', last_synced: null, last_error: null, configured: true }
      const h = mockDoor({ show_profile: profile(), status_summary: summary({ drive }), list_matches: matchesResult([]), doctor: doctorReport('ok'), sync_data: { action: 'pull' } })
      render(<App />)
      await screen.findByRole('heading', { name: 'Matches' })
      await waitFor(() => expect(h.call.mock.calls.filter((c) => c[0] === 'sync_data')).toEqual([['sync_data', {}]]))
      const profileReads = () => h.call.mock.calls.filter((c) => c[0] === 'show_profile').length
      await waitFor(() => expect(profileReads()).toBeGreaterThan(1))
      await act(() => new Promise((r) => setTimeout(r, 50))) // the summaries the sync asked for have come back
      expect(h.call.mock.calls.filter((c) => c[0] === 'sync_data')).toHaveLength(1)
    })

    it('a Drive that is off, or the phone, syncs nothing on opening', async () => {
      const h = gated(profile())
      render(<App />)
      await screen.findByRole('heading', { name: 'Matches' })
      await waitFor(() => expect(h.call.mock.calls.map((c) => c[0])).toContain('status_summary'))
      await act(() => new Promise((r) => setTimeout(r, 50)))
      expect(h.call.mock.calls.map((c) => c[0])).not.toContain('sync_data')
      cleanup()
      const drive = { connected: true, account: 'a@b.c', last_synced: null, last_error: null, configured: true }
      const phone = gated(profile(), { status_summary: summary({ drive }) })
      phone.info.mockResolvedValue({ demo: false, remote: true })
      render(<App />)
      await screen.findByRole('heading', { name: 'Matches' })
      await waitFor(() => expect(phone.call.mock.calls.map((c) => c[0])).toContain('status_summary'))
      await act(() => new Promise((r) => setTimeout(r, 50)))
      expect(phone.call.mock.calls.map((c) => c[0])).not.toContain('sync_data')
    })

    it('a Drive off on opening and connected later does not sync again on its own', async () => {
      let drive = { connected: false, account: null as string | null, last_synced: null, last_error: null, configured: true }
      const h = mockDoor({
        show_profile: profile(),
        status_summary: () => summary({ drive }),
        list_matches: matchesResult([]),
        doctor: doctorReport('ok'),
        connect_drive: () => {
          drive = { ...drive, connected: true, account: 'a@b.c' }
          return { account: 'a@b.c' }
        },
        sync_data: { action: 'push' },
      })
      render(<App />)
      await userEvent.click(await screen.findByRole('button', { name: 'Settings' }))
      const row = within(await screen.findByRole('listitem', { name: 'Google Drive' }))
      await userEvent.click(await row.findByRole('button', { name: 'Connect' }))
      await row.findByRole('button', { name: 'Disconnect' })
      await act(() => new Promise((r) => setTimeout(r, 50)))
      expect(h.call.mock.calls.filter((c) => c[0] === 'sync_data')).toHaveLength(1) // the connect's own
    })

    it('both sides changed on opening: a line opens Settings, where the Drive row asks which to keep', async () => {
      const drive = { connected: true, account: 'a@b.c', last_synced: null, last_error: null, configured: true }
      mockDoor({
        show_profile: profile(),
        status_summary: summary({ drive }),
        list_matches: matchesResult([]),
        doctor: doctorReport('ok'),
        sync_data: () => {
          throw { message: 'both changed', conflict: true }
        },
      })
      render(<App />)
      await userEvent.click(await (await sidebar()).findByRole('button', { name: 'Google Drive needs a choice' }))
      const row = within(await screen.findByRole('listitem', { name: 'Google Drive' }))
      expect(row.getByText(/both changed since they last synced/)).toBeInTheDocument()
      await userEvent.click(row.getByRole('button', { name: 'Not now' }))
      await waitFor(() => expect(lines().queryByRole('button', { name: 'Google Drive needs a choice' })).toBeNull())
    })

    it('something that keeps going wrong opens Settings at Report a problem', async () => {
      const h = mockDoor({ show_profile: profile(), status_summary: summary({ recurring_problem: true }), list_matches: matchesResult([]), doctor: doctorReport('ok') })
      render(<App />)
      await userEvent.click(await (await sidebar()).findByRole('button', { name: 'Something keeps going wrong. Send a report' }))
      const report = await screen.findByRole('region', { name: 'Report a problem' })
      expect(within(report).getByRole('button', { name: 'Save logs…' })).toBeVisible()
      expect(screen.getByRole('button', { name: 'Settings' })).toHaveAttribute('aria-current', 'page')
      expect(h.reportProblem).not.toHaveBeenCalled()
    })

    it('data that could not be upgraded is said at the sidebar even though every other tool refuses', async () => {
      const refusal = 'Your data could not be upgraded to this version: x. Nothing was changed. Send a report from Settings.'
      const refuse = () => {
        throw new Error(refusal)
      }
      const data = { state: 'failed', message: refusal }
      mockDoor({ show_profile: refuse, status_summary: refuse, list_matches: refuse, doctor: { ...doctorReport('ok'), data } })
      render(<App />)
      await userEvent.click(await (await sidebar()).findByRole('button', { name: 'Your data could not be upgraded. Send a report' }))
      expect(await screen.findByRole('region', { name: 'Report a problem' })).toBeInTheDocument()
    })

    it('a saved report reads the summary again, and the line goes', async () => {
      let recurring = true
      const h = mockDoor({ show_profile: profile(), status_summary: () => summary({ recurring_problem: recurring }), list_matches: matchesResult([]), doctor: doctorReport('ok') })
      render(<App />)
      await userEvent.click(await (await sidebar()).findByRole('button', { name: 'Something keeps going wrong. Send a report' }))
      const report = await screen.findByRole('region', { name: 'Report a problem' })
      recurring = false
      h.reportProblem.mockResolvedValueOnce({ ok: true, data: { path: '/Users/ada/Desktop/door-report-2026-10-26.zip', files: [], bytes: 1 } })
      await userEvent.click(within(report).getByRole('button', { name: 'Save logs…' }))
      await waitFor(() => expect(lines().queryByRole('button', { name: 'Something keeps going wrong. Send a report' })).toBeNull())
      expect(within(screen.getByRole('region', { name: 'Report a problem' })).getByText(/^Saved as door-report-2026-10-26\.zip\./)).toBeInTheDocument()
    })

    it('on the phone, something that keeps going wrong is not said: the report is made on the computer', async () => {
      const { info, call } = gated(profile(), { status_summary: summary({ recurring_problem: true }) })
      info.mockResolvedValue({ demo: false, remote: true })
      render(<App />)
      await screen.findByRole('heading', { name: 'Matches' })
      await waitFor(() => expect(call.mock.calls.map((c) => c[0])).toContain('status_summary'))
      await act(() => new Promise((r) => setTimeout(r, 50)))
      expect(screen.queryByText('Something keeps going wrong. Send a report')).toBeNull()
    })

    it('on the phone, the plan line is said, as plain text', async () => {
      const low = { as_of: new Date().toISOString(), status: 'allowed', five_hour: { used: 0.9 }, room: { find: 1, prepare: 2 }, binding: 'five_hour' }
      const { info } = gated(profile(), { status_summary: summary({ plan: low }) })
      info.mockResolvedValue({ demo: false, remote: true })
      render(<App />)
      const line = await screen.findByText('Room for about 2 more applications this window')
      expect(line.closest('button')).toBeNull()
    })

    it('what needs you stands above Find new jobs, read before a search starts', async () => {
      const low = { as_of: new Date().toISOString(), status: 'allowed', five_hour: { used: 0.9 }, room: { find: 1, prepare: 2 }, binding: 'five_hour' }
      mockDoor({ show_profile: profile(), status_summary: summary({ plan: low }), list_matches: matchesResult([]), doctor: doctorReport('ok') })
      render(<App />)
      const group = await (await sidebar()).findByRole('group', { name: 'Needs you' })
      const find = sidebarButton()
      expect(group.compareDocumentPosition(find) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    })

    it('the plan line goes by itself once the window resets, by one read at that time', async () => {
      const resets = new Date(Date.now() + 3_600_000)
      let after = false
      const low = { as_of: new Date().toISOString(), status: 'allowed', five_hour: { used: 0.9, resets_at: resets.toISOString() }, room: { find: 1, prepare: 2 }, binding: 'five_hour' }
      const { call } = gated(profile(), { status_summary: () => summary(after ? {} : { plan: low }) })
      const real = globalThis.setTimeout
      const timers: (() => void)[] = []
      // hold the long timer the app sets for the reset; every other one runs as usual
      vi.spyOn(globalThis, 'setTimeout').mockImplementation(((fn: () => void, ms?: number, ...rest: unknown[]) => {
        if (typeof ms === 'number' && ms > 3_000_000) {
          timers.push(fn)
          return 0 as unknown as ReturnType<typeof setTimeout>
        }
        return real(fn, ms, ...rest)
      }) as typeof setTimeout)
      try {
        render(<App />)
        await screen.findByText(/Room for about 2 more applications this window, resets/)
        await waitFor(() => expect(timers).toHaveLength(1))
        const before = call.mock.calls.filter((c) => c[0] === 'status_summary').length
        after = true
        await act(async () => timers[0]!())
        await waitFor(() => expect(screen.queryByText(/more applications this window/)).toBeNull())
        expect(call.mock.calls.filter((c) => c[0] === 'status_summary').length).toBe(before + 1)
      } finally {
        vi.restoreAllMocks()
      }
    })

    it('nothing is said when all is well', async () => {
      const { call } = gated(profile())
      render(<App />)
      await screen.findByRole('heading', { name: 'Matches' })
      await waitFor(() => expect(call.mock.calls.map((c) => c[0])).toContain('doctor'))
      expect(screen.queryByRole('group', { name: 'Needs you' })).toBeNull()
    })
  })

  it('a check again keeps the last answer until the new one, and an older answer never wins', async () => {
    let n = 0
    const answers: ((r: unknown) => void)[] = []
    const h = mockDoor({
      show_profile: profile(),
      status_summary: summary(),
      list_matches: matchesResult([]),
      doctor: () => {
        n += 1
        if (n === 1) return doctorReport('out')
        return new Promise((r) => answers.push(r))
      },
    })
    render(<App />)
    await userEvent.click(await within(await screen.findByRole('complementary')).findByRole('button', { name: 'Claude is not signed in' }))
    // opening Settings checks again: the line and the row keep saying signed out while it waits
    const claude = () => screen.getByRole('listitem', { name: 'Claude' })
    expect(claude()).toHaveTextContent('Not signed in')
    expect(within(screen.getByRole('complementary')).getByRole('button', { name: 'Claude is not signed in' })).toBeInTheDocument()
    await userEvent.click(within(claude()).getByRole('button', { name: 'Sign in with Claude' }))
    await act(async () => h.pushLogin({ state: 'done' }))
    expect(answers).toHaveLength(2)
    await act(async () => answers[1]!(doctorReport('ok')))
    await act(async () => answers[0]!(doctorReport('out')))
    expect(claude()).toHaveTextContent('Signed in')
    expect(within(screen.getByRole('complementary')).queryByRole('button', { name: 'Claude is not signed in' })).toBeNull()
  })

  describe('Drafting again (Profile → CV, no CV yet: Draft it from your CV file or pages)', () => {
    const example = () => profile({ cv: { ...existingProfile.cv, exists: false, text: null } })
    const draftAgain = async () => {
      await userEvent.click(await screen.findByRole('button', { name: 'Profile' }))
      await userEvent.click(await screen.findByRole('button', { name: 'CV' }))
      await userEvent.click(await screen.findByRole('button', { name: 'Draft it from your CV file or pages' }))
    }

    it('opens the same screens, the answers kept', async () => {
      gated(example())
      render(<App />)
      await draftAgain()
      expect(await screen.findByRole('heading', { name: 'Tell me about yourself' })).toBeInTheDocument()
      expect(screen.getByText('Your answers stay.')).toBeInTheDocument()
    })

    it('the first step can be left without changing anything, back on Profile', async () => {
      const { call } = gated(example())
      render(<App />)
      await draftAgain()
      await userEvent.click(await screen.findByRole('button', { name: 'Back' }))
      expect(await screen.findByRole('heading', { name: 'Profile', level: 1 })).toBeInTheDocument()
      expect(call.mock.calls.map((c) => c[0])).not.toContain('init_profile')
    })
  })
})
