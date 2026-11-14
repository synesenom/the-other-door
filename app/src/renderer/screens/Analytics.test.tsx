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
    const rows = within(part).getAllByRole('listitem').filter((li) => li.classList.contains('usage-activity'))
    expect(rows.map((r) => within(r).getByRole('heading').textContent)).toEqual(['Preparing applications', 'Finding jobs', 'Everything else'])
    expect(within(rows[0]).getByText('1 application prepared')).toBeInTheDocument()
    expect(within(rows[1]).getByText('110 postings scored')).toBeInTheDocument()
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
    expect(await screen.findByText('1 other request')).toBeInTheDocument()
    expect(screen.getByText('≈ <$0.01')).toBeInTheDocument()
    expect(screen.getByText('<$0.01')).toBeInTheDocument()
  })

  it('before any call: one quiet line', async () => {
    mockDoor({ status_summary: summary({ cost: null, plan: null }) })
    render(<Analytics />)
    expect(await screen.findByText(/shows here after your first search/)).toBeInTheDocument()
  })
})
