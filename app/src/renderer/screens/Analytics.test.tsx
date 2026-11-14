// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { mockDoor } from '../testing'
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

  describe('Applications', () => {
    const FUNNEL = [
      { stage: 'postings', count: 200 }, { stage: 'applicable', count: 120 }, { stage: 'matches', count: 40 },
      { stage: 'prepared', count: 10 }, { stage: 'applied', count: 4 }, { stage: 'interview', count: 2 }, { stage: 'offer', count: 1 },
    ]
    const OUT = { passed: 1, rejected: 0, ghosted: 0, withdrawn: 0, pending: 1 }
    const APPLIED = {
      funnel: FUNNEL,
      application: OUT,
      interviews: { screening: { passed: 0, rejected: 1, ghosted: 0, withdrawn: 0, pending: 0 } },
      pass_rates: {
        application: { passed: 1, decided: 2, rate: 0.5, low: 0.21, high: 0.79 },
        screening: { passed: 0, decided: 1, rate: null, low: null, high: null },
      },
    }

    it('shows one bar row per funnel stage with its label and count', async () => {
      mockDoor({ status_summary: summary({ ...APPLIED, cost: null }) })
      render(<Analytics />)
      const part = await screen.findByRole('region', { name: 'Applications' })
      const rows = within(part).getAllByRole('listitem').filter((li) => li.classList.contains('funnel-row'))
      expect(rows.map((r) => r.textContent)).toEqual([
        'Scraped200', 'Worth a look120', 'Matches40', 'Prepared10', 'Applied4', 'Interview2', 'Offer1'])
      expect(within(rows[2]).getByRole('img', { name: 'Matches: 40 of 200' })).toBeInTheDocument()
    })

    it('says how the application and each round went with the pass rate and its interval', async () => {
      mockDoor({ status_summary: summary({ ...APPLIED, cost: null }) })
      render(<Analytics />)
      const part = await screen.findByRole('region', { name: 'Applications' })
      const application = within(part).getByRole('row', { name: /Application/ })
      expect(application).toHaveTextContent('1/2 passed')
      expect(application).toHaveTextContent('50% (21–79%)')
      // passed, rejected, ghosted, withdrawn, pending, then the rate
      expect(within(application).getAllByRole('cell').map((c) => c.textContent)).toEqual(['1', '0', '0', '0', '1', '1/2 passed  50% (21–79%)'])
      expect(within(part).getByRole('row', { name: /Screening/ }).textContent).not.toContain('%')
    })

    it('with something found but nothing applied: the bars, and one quiet line where the table goes', async () => {
      const funnel = FUNNEL.map((f) => ({ ...f, count: { postings: 5, applicable: 4, matches: 3, prepared: 2 }[f.stage] ?? 0 }))
      mockDoor({ status_summary: summary({ cost: COST, plan: null, funnel, application: { ...OUT, passed: 0, pending: 0 }, interviews: {}, pass_rates: {} }) })
      render(<Analytics />)
      const part = await screen.findByRole('region', { name: 'Applications' })
      expect(within(part).getByRole('img', { name: 'Prepared: 2 of 5' })).toBeInTheDocument()
      expect(within(part).getByText('How each stage went shows here once you have applied')).toBeInTheDocument()
      expect(within(part).queryByRole('table')).toBeNull()
      expect(screen.getByText('≈ $2.10')).toBeInTheDocument()
    })

    it('with nothing scraped: a single quiet line for the section', async () => {
      const funnel = FUNNEL.map((f) => ({ ...f, count: 0 }))
      mockDoor({ status_summary: summary({ cost: COST, plan: null, funnel, application: OUT, interviews: {}, pass_rates: {} }) })
      render(<Analytics />)
      const part = await screen.findByRole('region', { name: 'Applications' })
      expect(within(part).getByText('Your funnel shows here once jobs are found')).toBeInTheDocument()
      expect(within(part).queryAllByRole('img')).toEqual([])
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

    it('a summary without a funnel: no section, no crash, usage still shows', async () => {
      mockDoor({ status_summary: summary({ cost: COST, plan: null }) })
      render(<Analytics />)
      expect(await screen.findByText('≈ $2.10')).toBeInTheDocument()
      expect(screen.queryByRole('region', { name: 'Applications' })).toBeNull()
    })

    it('a stage it has no label for is skipped', async () => {
      mockDoor({ status_summary: summary({ ...APPLIED, funnel: [...FUNNEL, { stage: 'mystery', count: 1 }], cost: null }) })
      render(<Analytics />)
      const part = await screen.findByRole('region', { name: 'Applications' })
      expect(within(part).getAllByRole('img')).toHaveLength(7)
      expect(within(part).queryByText(/mystery/)).toBeNull()
    })
  })
})
