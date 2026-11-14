// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { mockDoor as baseDoor } from '../testing'
import { Analytics, usd } from './Analytics'

afterEach(cleanup)

const COST = {
  days: 7,
  usd: 2.1,
  per_run: { find: 0.31, prepare: 1.42 },
  activities: [
    { activity: 'prepare', label: 'Preparing applications', usd: 1.5, count: 1, of: 'applications prepared',
      features: [{ feature: 'tailoring', label: 'Tailoring the CV and letter', usd: 1.4, calls: 1 }, { feature: 'revise', label: 'Revising materials', usd: 0.1, calls: 1 }] },
    { activity: 'find', label: 'Finding jobs', usd: 0.5, count: 110, of: 'postings scored',
      features: [{ feature: 'match_scoring', label: 'Scoring postings', usd: 0.5, calls: 3 }] },
    { activity: 'other', label: 'Everything else', usd: 0.1, count: 2, of: 'other requests',
      features: [{ feature: 'ask', label: 'Questions about your jobs', usd: 0.1, calls: 2 }] },
  ],
}
const MARKET = {
  counts: { scraped: 10, scored: 5, above_min_score: 2 },
  skills: [{ name: 'SQL', count: 6, share: 0.6, have: true }],
  uncovered_titles: [],
  companies: { population: 'scraped', rows: [] },
}
/** Every Analytics opening also reads the market once. */
const mockDoor = (given: Record<string, unknown>) => baseDoor({ market: MARKET, ...given })
const RESETS = new Date(Date.now() + 2 * 3600e3).toISOString()
const PLAN = { as_of: new Date().toISOString(), status: 'allowed', five_hour: { used: 0.42, resets_at: RESETS }, room: { find: 6, prepare: 2 }, binding: 'five_hour' }

function summary(over: Record<string, unknown>) {
  return { min_score: 0.6, since_last_review: { last_reviewed_at: null, runs: 0, new_matches: 0, site_failures: [] }, in_progress: null, ...over }
}

describe('usd', () => {
  it('reads dollars and cents, a sliver as under a cent', () => {
    expect([0, 0.004, 0.012, 1.5, 1234.5].map(usd)).toEqual(['$0.00', '<$0.01', '$0.01', '$1.50', '$1,234.50'])
  })
})

describe('Analytics', () => {
  it('says what each activity cost at API prices, largest first, with what it did', async () => {
    mockDoor({ status_summary: summary({ cost: COST, plan: PLAN }) })
    render(<Analytics />)
    const part = await screen.findByRole('region', { name: 'Claude usage' })
    // an estimate, marked as one, and plainly not something to pay
    expect(within(part).getByText('≈ $2.10')).toBeInTheDocument()
    const notice = within(part).getByText("You don't pay this.")
    expect(notice.tagName).toBe('STRONG')
    expect(notice.parentElement).toHaveTextContent("You don't pay this. Your Claude plan covers it. The last 7 days, estimated at API prices.")
    expect(within(part).getByText('About $0.31 a search, $1.42 an application')).toBeInTheDocument()
    // one bar for the whole total, a part per activity sized by its share, its tone matching the activity's dot
    const stack = within(part).getByRole('img', { name: 'Preparing applications 71%, Finding jobs 24%, Everything else 5%' })
    const parts = [...stack.children] as HTMLElement[]
    expect(parts.map((p) => p.style.flexGrow)).toEqual(['0.714', '0.238', '0.048'])
    const rows = within(part).getAllByRole('listitem').filter((li) => li.classList.contains('usage-activity'))
    // what each did after its name, as Finding jobs puts a site's jobs after it
    expect(rows.map((r) => within(r).getByRole('heading').textContent)).toEqual([
      'Preparing applications · 1 application prepared', 'Finding jobs · 110 postings scored', 'Everything else · 2 other requests'])
    rows.forEach((r, i) => expect(r.querySelector('.usage-dot')!.className).toContain(parts[i].className))
    // the features within an activity, only when there are several
    expect(within(rows[0]).getByText('Tailoring the CV and letter')).toBeInTheDocument()
    expect(within(rows[1]).queryByText('Scoring postings')).toBeNull()
  })

  it('says nothing of the plan window: a live reading, not what the week cost', async () => {
    mockDoor({ status_summary: summary({ cost: COST, plan: PLAN }) })
    render(<Analytics />)
    await screen.findByText('≈ $2.10')
    expect(screen.queryByText(/window used/)).toBeNull()
    expect(screen.queryByText(/room for about/)).toBeNull()
  })

  it('nothing in the window: says so, and still what one run costs', async () => {
    mockDoor({ status_summary: summary({ cost: { days: 7, usd: 0, per_run: { find: 0.3, prepare: null }, activities: [] }, plan: null }) })
    render(<Analytics />)
    expect(await screen.findByText('Nothing in the last 7 days')).toBeInTheDocument()
    expect(screen.getByText('About $0.30 a search')).toBeInTheDocument()
  })

  it('one of a kind in the singular, a sliver as under a cent', async () => {
    const one = { days: 7, usd: 0.003, per_run: { find: null, prepare: null }, activities: [
      { activity: 'other', label: 'Everything else', usd: 0.003, count: 1, of: 'other requests', features: [{ feature: 'ask', label: 'Questions about your jobs', usd: 0.003, calls: 1 }] }] }
    mockDoor({ status_summary: summary({ cost: one, plan: null }) })
    render(<Analytics />)
    expect(await screen.findByText('· 1 other request')).toBeInTheDocument()
    expect(screen.getByText('≈ <$0.01')).toBeInTheDocument()
    expect(screen.getByText('<$0.01')).toBeInTheDocument()
  })

  it('before any call: one quiet line', async () => {
    mockDoor({ status_summary: summary({ cost: null, plan: null }) })
    render(<Analytics />)
    expect(await screen.findByText(/shows here after your first search/)).toBeInTheDocument()
  })

  it('shows the Market third, read once on opening, listed beside the sections', async () => {
    const { call } = mockDoor({ status_summary: summary({ cost: COST, standing: { offer: 0, interviewing: 0, waiting: 1, rejected: 0, ghosted: 0, withdrawn: 0 } }) })
    render(<Analytics />)
    await screen.findByRole('region', { name: 'Applications' })
    const headings = (await screen.findAllByRole('heading', { level: 2 })).map((h) => h.textContent)
    expect(headings).toEqual(['Applications', 'Claude usage', 'Market'])
    expect(await screen.findByRole('listitem', { name: 'SQL, in your CV' })).toBeInTheDocument()
    expect(call.mock.calls.filter((c) => c[0] === 'market')).toEqual([['market', { save: false }]])
    expect(screen.getAllByText('Market')).toHaveLength(2) // the heading and its entry beside the sections
  })

  it('without the applications the Market is still the last section', async () => {
    mockDoor({ status_summary: summary({ cost: COST }) })
    render(<Analytics />)
    await screen.findByText('≈ $2.10')
    expect((await screen.findAllByRole('heading', { level: 2 })).map((h) => h.textContent)).toEqual(['Claude usage', 'Market'])
  })

  describe('Applications', () => {
    const PIPELINE = { total: 200, excluded: 0, applicable: 120, above_threshold: 40, unapplied: 20,
      above_threshold_by_status: { unapplied: 20, prepared: 3, applied: 7, discarded: 10 } }
    const STANDING = { offer: 1, interviewing: 2, waiting: 2, rejected: 1, ghosted: 1, withdrawn: 0 }
    const RATE = { application: { passed: 3, decided: 5, rate: 0.6, low: 0.4, high: 0.77 } }
    const APPLIED = { pipeline: PIPELINE, standing: STANDING, pass_rates: RATE }
    const legend = (block: HTMLElement) => within(block).getAllByRole('listitem').map((li) => li.textContent)

    it('leads with the interview rate of the answered applications, with its likely range', async () => {
      mockDoor({ status_summary: summary({ ...APPLIED, cost: null }) })
      render(<Analytics />)
      const part = await screen.findByRole('region', { name: 'Applications' })
      expect(within(part).getByText('60%')).toBeInTheDocument()
      expect(part).toHaveTextContent('of your applications with an outcome (an interview, a rejection or no reply) led to an interview: 3 of 5, likely between 40% and 77%.')
    })

    it('shows no split of your matches: the Matches list has them', async () => {
      mockDoor({ status_summary: summary({ ...APPLIED, cost: null }) })
      render(<Analytics />)
      await screen.findByRole('group', { name: 'Your applications' })
      expect(screen.queryByRole('group', { name: 'Your matches' })).toBeNull()
      expect(screen.queryByText(/set aside/)).toBeNull()
    })

    it('splits your applications by where each stands now; a stand no application is in is left out', async () => {
      mockDoor({ status_summary: summary({ ...APPLIED, cost: null }) })
      render(<Analytics />)
      const block = await screen.findByRole('group', { name: 'Your applications' })
      expect(within(block).getByRole('heading')).toHaveTextContent('Your applications · 7')
      expect(legend(block)).toEqual(['Offer1', 'Interviewing2', 'Waiting for an answer2', 'Rejected or no answer2'])
      cleanup()
      mockDoor({ status_summary: summary({ ...APPLIED, standing: { ...STANDING, offer: 0, withdrawn: 1 }, cost: null }) })
      render(<Analytics />)
      expect(legend(await screen.findByRole('group', { name: 'Your applications' }))).toEqual(
        ['Interviewing2', 'Waiting for an answer2', 'Rejected, no answer or withdrawn3'])
    })

    it('before any answer: no rate, a line saying when it shows', async () => {
      mockDoor({ status_summary: summary({ ...APPLIED, standing: { ...STANDING, offer: 0, interviewing: 0, rejected: 0, ghosted: 0 }, pass_rates: {}, cost: null }) })
      render(<Analytics />)
      const part = await screen.findByRole('region', { name: 'Applications' })
      expect(within(part).getByText('Your interview rate shows here once an application has an outcome.')).toBeInTheDocument()
      expect(within(part).queryByText(/%$/)).toBeNull()
    })

    it('with nothing sent: a single quiet line for the section, whatever the matches', async () => {
      mockDoor({ status_summary: summary({ ...APPLIED, standing: { ...STANDING, offer: 0, interviewing: 0, waiting: 0, rejected: 0, ghosted: 0 }, pass_rates: {}, cost: COST, plan: null }) })
      render(<Analytics />)
      const part = await screen.findByRole('region', { name: 'Applications' })
      expect(within(part).getByText('Your applications show here once you send one.')).toBeInTheDocument()
      expect(within(part).queryAllByRole('img')).toEqual([])
      expect(within(part).queryByText(/interview rate/)).toBeNull()
      expect(screen.getByText('≈ $2.10')).toBeInTheDocument()
    })

    it('a failed read shows no error and no section; a read that works shows the section', async () => {
      mockDoor({})
      const { unmount } = render(<Analytics />)
      expect(await screen.findByRole('heading', { name: 'Analytics' })).toBeInTheDocument()
      await new Promise((r) => setTimeout(r, 20))
      expect(screen.queryByRole('alert')).toBeNull()
      expect(screen.queryByRole('region', { name: 'Applications' })).toBeNull()
      unmount()
      mockDoor({ status_summary: summary({ ...APPLIED, cost: null }) })
      render(<Analytics />)
      expect(await screen.findByRole('region', { name: 'Applications' })).toBeInTheDocument()
      expect(screen.queryByRole('alert')).toBeNull()
    })

    it('a summary without standing: no section, no crash, usage still shows', async () => {
      mockDoor({ status_summary: summary({ cost: COST, plan: null }) })
      render(<Analytics />)
      expect(await screen.findByText('≈ $2.10')).toBeInTheDocument()
      expect(screen.queryByRole('region', { name: 'Applications' })).toBeNull()
    })
  })
})
