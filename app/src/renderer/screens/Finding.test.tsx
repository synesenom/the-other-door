// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RunBoard, RunRecord } from '../api'
import { mockDoor } from '../testing'
import { Finding, type FindingState } from './Finding'

afterEach(cleanup)

const STARTED = '2026-10-29T08:02:00+00:00'
const hhmm = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

const board = (over: Partial<Extract<RunBoard, { active: true }>> = {}): RunBoard => ({
  active: true,
  own: true,
  started_at: STARTED,
  purpose: 'run',
  message: 'collect: reading',
  steps: [
    { name: 'search', status: 'done', detail: '142 postings from 6 boards', started_at: '2026-10-29T08:02:00+00:00', finished_at: '2026-10-29T08:05:00+00:00' },
    { name: 'discover', status: 'skipped', detail: '--skip' },
    { name: 'follow', status: 'done', detail: '11 followed', started_at: '2026-10-29T08:05:00+00:00', finished_at: '2026-10-29T08:09:00+00:00' },
    { name: 'collect', status: 'running', detail: '', started_at: '2026-10-29T08:09:00+00:00', done: 23, total: 57, hosts: ['Novo Nordisk'], sites: { greenhouse: 12, lever: 4 } },
    { name: 'match', status: 'waiting', detail: '' },
  ],
  ...over,
})

const handlers = () => ({ onStart: vi.fn(), onStop: vi.fn(), onViewMatches: vi.fn() })
const show = (state: FindingState, b: RunBoard = board(), h = handlers()) => {
  render(<Finding state={state} board={b} {...h} />)
  return h
}

describe('Finding, the discovery sources nobody chose', () => {
  const unchosen = [{ key: 'linkedin_discovery', label: 'LinkedIn' }, { key: 'hellowork_discovery', label: 'HelloWork' }]
  const skipped = (detail: string) =>
    board({ steps: board().active ? (board() as Extract<RunBoard, { active: true }>).steps.map((st) => (st.name === 'discover' ? { ...st, detail } : st)) : [] })

  it('says so under Discover, a line each with a warning mark, whose enable opens Profile', async () => {
    mockDoor({})
    const onChooseDiscovery = vi.fn()
    render(<Finding state={{ kind: 'running' }} board={skipped('linkedin_discovery not chosen; hellowork_discovery not chosen')} {...handlers()} discoveryUnchosen={unchosen} onChooseDiscovery={onChooseDiscovery} />)
    const row = screen.getByRole('heading', { name: 'Discover' }).closest('li')!
    expect(row).not.toHaveTextContent('linkedin_discovery')
    const lines = within(row).getByRole('list', { name: 'Discover sources' }) // one list, in its two columns
    expect(within(lines).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['LinkedIn (not enabled, enable)', 'HelloWork (not enabled, enable)'])
    expect(lines.querySelectorAll('.warning-mark')).toHaveLength(2)
    await userEvent.click(within(row).getByRole('button', { name: 'Enable HelloWork' }))
    expect(onChooseDiscovery).toHaveBeenCalled()
  })

  it('a source the user turned off is just skipped, without its config key', () => {
    mockDoor({})
    render(<Finding state={{ kind: 'running' }} board={skipped('linkedin_discovery is off; hellowork_discovery is off')} {...handlers()} discoveryUnchosen={[]} />)
    const row = screen.getByRole('heading', { name: 'Discover' }).closest('li')!
    expect(row).toHaveTextContent('Skipped')
    expect(row).not.toHaveTextContent('_discovery')
  })

  it('says nothing while Discover is still waiting its turn', () => {
    mockDoor({})
    const waiting = board({ steps: [{ name: 'search', status: 'running', detail: '' }, { name: 'discover', status: 'waiting', detail: '' }] })
    render(<Finding state={{ kind: 'running' }} board={waiting} {...handlers()} discoveryUnchosen={unchosen} />)
    expect(screen.queryByText(/not enabled/)).toBeNull()
  })

  it('says nothing when every source was chosen', () => {
    mockDoor({})
    show({ kind: 'running' })
    expect(screen.queryByText(/not enabled/)).toBeNull()
  })
})

describe('Finding, a run going', () => {
  it('shows the title, when it started, and the five steps in order', () => {
    mockDoor({})
    show({ kind: 'running' })
    expect(screen.getByRole('heading', { name: 'Finding jobs', level: 1 })).toHaveClass('display-l')
    expect(screen.getByText(new RegExp(`Started ${hhmm(STARTED)}`))).toBeInTheDocument()
    expect(screen.getByText(/quitting .*stops it/)).toBeInTheDocument()
    const rows = within(screen.getByRole('list', { name: 'Steps' })).getAllByRole('listitem')
    expect(rows.map((r) => within(r).getByRole('heading').textContent)).toEqual(['Search', 'Discover', 'Follow', 'Collect', 'Match'])
  })

  it('draws done with a check, running with its number, a bar and its work, waiting quietly', () => {
    mockDoor({})
    show({ kind: 'running' })
    const [search, discover, , collect, match] = within(screen.getByRole('list', { name: 'Steps' })).getAllByRole('listitem')
    expect(search!.querySelector('.check-mark')).toBeInTheDocument()
    expect(within(search).getByText('142 postings from 6 boards')).toBeInTheDocument()
    expect(within(search).getByText('3 min')).toBeInTheDocument()
    expect(within(search).queryByRole('progressbar')).toBeNull()
    expect(within(discover).getByText('Skipped: left out of this run')).toBeInTheDocument()
    expect(within(collect).getByText('4')).toBeInTheDocument()
    expect(within(collect).getByText('Reading Novo Nordisk · 23 of 57 employers')).toBeInTheDocument()
    expect(within(collect).getByRole('progressbar')).toHaveAttribute('aria-valuenow', String(Math.round((23 / 57) * 100)))
    expect(within(collect).getByText('greenhouse 12')).toBeInTheDocument()
    expect(within(match).getByText('Scores the new ads against your CV')).toBeInTheDocument()
    expect(within(match).queryByRole('progressbar')).toBeNull()
  })

  it('says in words what Discover does, with no page count and no bar (its sources list shows how far it got)', () => {
    mockDoor({})
    const items = [{ id: 'linkedin', name: 'LinkedIn', state: 'running' as const }]
    const row = (request: string) => board({ steps: [{ name: 'discover', status: 'running', detail: '', request, requests: [9, 15], items }] })
    render(<Finding state={{ kind: 'running' }} board={row('page 9/15')} {...handlers()} />)
    const discover = within(screen.getByRole('list', { name: 'Steps' })).getAllByRole('listitem')[0]!
    expect(within(discover).getByText('Searching LinkedIn')).toBeInTheDocument()
    expect(within(discover).queryByText(/9\/15|page/)).toBeNull()
    expect(within(discover).queryByRole('progressbar')).toBeNull()
    cleanup()
    render(<Finding state={{ kind: 'running' }} board={row('job page 9/15')} {...handlers()} />)
    expect(screen.getByText('Reading job pages on LinkedIn')).toBeInTheDocument()
  })

  it('lists the boards a running step reads, each checked when done', () => {
    mockDoor({})
    const items = [{ id: 'jobindex', name: 'Jobindex', state: 'done' as const }, { id: 'thehub', name: 'The Hub', state: 'running' as const }, { id: 'euraxess', name: 'EURAXESS', state: 'waiting' as const }]
    const b = board()
    if (b.active) b.steps[3] = { ...b.steps[3], items }
    show({ kind: 'running' }, b)
    const list = screen.getByRole('list', { name: 'Collect sources' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows.map((r) => r.textContent)).toEqual(['Jobindex', 'The Hub', 'EURAXESS'])
    expect(rows[0]!.querySelector('.check-mark')).toBeInTheDocument()
  })

  it('puts the count of postings beside each board, not in a line of its own', () => {
    mockDoor({})
    const items = [{ id: 'jobindex', name: 'Jobindex', state: 'done' as const }, { id: 'thehub', name: 'The Hub', state: 'running' as const }, { id: 'euraxess', name: 'EURAXESS', state: 'done' as const }]
    const b = board()
    if (b.active) b.steps[3] = { ...b.steps[3], items, sites: { jobindex: 14, thehub: 3, euraxess: 0, novo: 2 } }
    show({ kind: 'running' }, b)
    const rows = within(screen.getByRole('list', { name: 'Collect sources' })).getAllByRole('listitem')
    expect(rows.map((r) => r.textContent)).toEqual(['Jobindex · 14', 'The Hub · 3', 'EURAXESS']) // nothing found: no 0
    const collect = screen.getByRole('heading', { name: 'Collect' }).closest('li')!
    expect(within(collect).queryByText('jobindex 14')).toBeNull()
    expect(within(collect).getByText('novo 2')).toBeInTheDocument() // one not in the list keeps the line
  })

  it('says beside a board at work what it is doing, so a count standing still never looks stuck', () => {
    mockDoor({})
    const items = [
      { id: 'jobindex', name: 'Jobindex', state: 'running' as const, activity: { kind: 'reading' as const, keyword: 'data', done: 12, total: 40 } },
      { id: 'thehub', name: 'The Hub', state: 'done' as const },
    ]
    const b = board()
    if (b.active) b.steps[3] = { ...b.steps[3], items, sites: { jobindex: 40 } }
    show({ kind: 'running' }, b)
    const rows = within(screen.getByRole('list', { name: 'Collect sources' })).getAllByRole('listitem')
    expect(rows.map((r) => r.textContent)).toEqual(["Jobindex · 40 · reading ads for 'data' (12 of 40)", 'The Hub'])
  })

  it('hides the list once every board is read, and on a finished step', () => {
    mockDoor({})
    const items = [{ id: 'linkedin', name: 'LinkedIn', state: 'done' as const }, { id: 'hellowork', name: 'HelloWork', state: 'done' as const }]
    const b = board()
    if (b.active) {
      b.steps[3] = { ...b.steps[3], items }
      b.steps[0] = { ...b.steps[0], items }
    }
    show({ kind: 'running' }, b)
    expect(screen.queryByRole('list', { name: 'Collect sources' })).toBeNull()
    expect(screen.queryByRole('list', { name: 'Search sources' })).toBeNull()
    expect(screen.queryByText('LinkedIn')).toBeNull()
  })

  it('has no bar for a running step without a total', () => {
    mockDoor({})
    const b = board()
    if (b.active) b.steps[3] = { name: 'collect', status: 'running', detail: '', started_at: STARTED, done: 2, hosts: [] }
    show({ kind: 'running' }, b)
    expect(screen.queryByRole('progressbar')).toBeNull()
  })

  it('offers Stop for a run of its own on the line of the title, explained on hover; it says Stopping…', async () => {
    mockDoor({})
    const h = show({ kind: 'running' })
    const stop = screen.getByRole('button', { name: 'Stop' })
    expect(stop).toHaveAccessibleDescription(/Nothing is lost: the next run picks up where this one stopped/)
    expect(stop.closest('.finding-head')).toHaveTextContent(/Finding jobs/)
    await userEvent.click(stop)
    expect(h.onStop).toHaveBeenCalledTimes(1)
    expect(await screen.findByRole('button', { name: 'Stopping…' })).toBeDisabled()
  })

  it('shows a run started elsewhere read-only: no Stop', () => {
    mockDoor({})
    show({ kind: 'running' }, board({ own: false }))
    expect(screen.getByText(new RegExp(`A run started elsewhere is in progress \\(started ${hhmm(STARTED)}\\)`))).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Stop/ })).toBeNull()
    expect(screen.getAllByRole('listitem').length).toBeGreaterThanOrEqual(5)
  })

  it('shows five waiting steps before the first board arrives', () => {
    mockDoor({})
    show({ kind: 'running' }, { active: false })
    expect(within(screen.getByRole('list', { name: 'Steps' })).getAllByRole('listitem')).toHaveLength(5)
  })

})

describe('Finding, other states', () => {
  it('an error says that The other door could not start the run', () => {
    mockDoor({})
    show({ kind: 'error', message: 'profile/config.json is missing' }, { active: false })
    expect(screen.getByRole('alert')).toHaveTextContent('The other door could not start the run: profile/config.json is missing')
  })

})

const record = (over: Partial<RunRecord> = {}): RunRecord => ({
  started_at: STARTED,
  finished_at: '2026-10-29T08:21:00+00:00',
  elapsed_s: 1140,
  steps: ['search', 'follow', 'collect', 'match'],
  skipped: {},
  search: {
    sites: [
      { site: 'jobindex', outcome: 'ok', count: 24 },
      { site: 'thehub', outcome: 'empty', count: 0 },
      { site: 'jobbank', outcome: 'resting', count: 0, until: '2026-10-30T08:00:00+00:00' },
    ],
  },
  collect: { sites: [{ site: 'teamtailor', outcome: 'failed', count: 0, errors: ['timeout', 'HTTP 503'] }] },
  match: { failed: ['jobindex.9', 'jobindex.10', 'jobindex.11'] },
  new_above_threshold: ['a.1', 'a.2'],
  top: [
    { id: 'a.1', score: 0.86, title: 'Finance Controller', company: 'Tyrell Maritime' },
    { id: 'a.2', score: 0.73, title: 'Business Controller', company: 'Wonka Pharma' },
  ],
  failures: ['teamtailor', 'jobindex.9'],
  ...over,
})

describe('Finding, the summary card', () => {
  it('says how many new matches, lists the top ones and takes you to them', async () => {
    mockDoor({})
    const h = show({ kind: 'summary', record: record() }, { active: false })
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('2 new matches')
    expect(screen.getByText('Finance Controller')).toBeInTheDocument()
    expect(screen.getByText(/Tyrell Maritime/)).toBeInTheDocument()
    expect(screen.getByText('0.86')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'View matches' }))
    expect(h.onViewMatches).toHaveBeenCalledTimes(1)
  })

  it('says one new match, or none, in words', () => {
    mockDoor({})
    show({ kind: 'summary', record: record({ new_above_threshold: ['a.1'], top: [] }) }, { active: false })
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('1 new match')
    cleanup()
    show({ kind: 'summary', record: record({ new_above_threshold: [], top: [] }) }, { active: false })
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('No new matches')
  })

  it('shows how long it took, opens the run record', async () => {
    const { showRun } = mockDoor({})
    show({ kind: 'summary', record: record() }, { active: false })
    expect(screen.getByText(/19 min/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show run record' }))
    expect(showRun).toHaveBeenCalledWith(STARTED)
  })

})

describe('Finding, the summary card of a run with no new matches', () => {
  const none = (over: Partial<RunRecord> = {}) =>
    record({
      search: { sites: [{ site: 'jobindex', outcome: 'ok', count: 900 }, { site: 'thehub', outcome: 'failed', count: 5 }] },
      collect: { sites: [{ site: 'teamtailor', outcome: 'ok', count: 17 }] },
      match: { scored: 40, above_threshold: 0, min_score: 0.65 },
      new_above_threshold: [],
      top: [],
      ...over,
    })
  const open = (r: RunRecord, extra: Record<string, unknown> = {}) => {
    mockDoor({})
    const cb = { onFollowEmployers: vi.fn(), onLowerBar: vi.fn(), onCheckSearch: vi.fn() }
    render(<Finding state={{ kind: 'summary', record: r }} board={{ active: false }} {...handlers()} {...cb} {...extra} />)
    return cb
  }

  it('says the run in one line, counting only the sites that worked', () => {
    open(none())
    expect(screen.getByText('917 jobs found, 40 close enough to score, none reached your bar (65%)')).toBeInTheDocument()
  })

  it('offers the next steps as actions', async () => {
    const cb = open(none())
    await userEvent.click(screen.getByRole('button', { name: 'Follow employers' }))
    await userEvent.click(screen.getByRole('button', { name: 'Lower the bar' }))
    await userEvent.click(screen.getByRole('button', { name: 'Check your search terms' }))
    expect(cb.onFollowEmployers).toHaveBeenCalledTimes(1)
    expect(cb.onLowerBar).toHaveBeenCalledTimes(1)
    expect(cb.onCheckSearch).toHaveBeenCalledTimes(1)
  })

  it('offers no action it cannot open', () => {
    mockDoor({})
    show({ kind: 'summary', record: none() }, { active: false })
    expect(screen.queryByRole('button', { name: 'Lower the bar' })).toBeNull()
  })

  it('says the next full run reads career sites only when this one skipped those steps', () => {
    open(none())
    expect(screen.queryByText(/career sites/)).toBeNull()
    cleanup()
    open(none({ skipped: { collect: '--skip' } }))
    expect(screen.getByText("The next full run also reads employers' own career sites.")).toBeInTheDocument()
  })

  it('says only No new matches when the record has no match counts', () => {
    open(none({ match: null }))
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('No new matches')
    expect(screen.queryByText(/jobs found/)).toBeNull()
    cleanup()
    open(none({ match: {} }))
    expect(screen.queryByText(/jobs found/)).toBeNull()
  })

  it('says one job in the singular', () => {
    open(none({ search: { sites: [{ site: 'jobindex', outcome: 'ok', count: 1 }] }, collect: null }))
    expect(screen.getByText(/^1 job found, /)).toBeInTheDocument()
  })

  it('has no account or actions when there are new matches', () => {
    open(record())
    expect(screen.queryByText(/jobs found/)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Lower the bar' })).toBeNull()
  })
})

describe('Finding, the reminder about discovery after a first run with few matches', () => {
  const off = [{ key: 'linkedin_discovery', label: 'LinkedIn' }, { key: 'hellowork_discovery', label: 'HelloWork' }]
  const few = record({ new_above_threshold: ['a.1'], top: [] })
  const summary = (r: RunRecord, firstRun: boolean, discoveryOff = off, onChooseDiscovery = vi.fn()) => {
    render(<Finding state={{ kind: 'summary', record: r, firstRun }} board={{ active: false }} {...handlers()} discoveryOff={discoveryOff} onChooseDiscovery={onChooseDiscovery} />)
    return onChooseDiscovery
  }

  it('says the sources can find employers, at your own risk, with the disclaimer and the setting', async () => {
    mockDoor({})
    const onChoose = summary(few, true)
    const line = screen.getByRole('note', { name: 'Employer discovery' })
    expect(line).toHaveTextContent(/can also find employers on LinkedIn and HelloWork/)
    expect(line).toHaveTextContent(/terms forbid automated access/)
    await userEvent.click(within(line).getByRole('button', { name: 'legal disclaimer' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    await userEvent.click(within(line).getByRole('button', { name: 'Turn it on in Settings' }))
    expect(onChoose).toHaveBeenCalled()
  })

  it('also shows after a first run with no matches at all', () => {
    mockDoor({})
    summary(record({ new_above_threshold: [], top: [] }), true)
    expect(screen.getByRole('note', { name: 'Employer discovery' })).toBeInTheDocument()
  })

  it('says nothing after a first run with enough matches', () => {
    mockDoor({})
    summary(record({ new_above_threshold: ['a.1', 'a.2', 'a.3'], top: [] }), true)
    expect(screen.queryByRole('note', { name: 'Employer discovery' })).toBeNull()
  })

  it('says nothing after a later run, or with no source off', () => {
    mockDoor({})
    summary(few, false)
    expect(screen.queryByRole('note', { name: 'Employer discovery' })).toBeNull()
    cleanup()
    summary(few, true, [])
    expect(screen.queryByRole('note', { name: 'Employer discovery' })).toBeNull()
  })
})

