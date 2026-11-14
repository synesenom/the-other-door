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
    expect(within(part).getByText('$2.10')).toBeInTheDocument()
    expect(within(part).getByText(/not charged per call/)).toBeInTheDocument()
    expect(within(part).getByText(/One search for new jobs about \$0\.31/)).toBeInTheDocument()
    expect(within(part).getByText(/one prepared application about \$1\.42/)).toBeInTheDocument()
    const rows = within(part).getAllByRole('listitem').filter((li) => li.classList.contains('usage-activity'))
    expect(rows.map((r) => within(r).getByRole('heading').textContent)).toEqual(['Preparing applications', 'Finding jobs', 'Everything else'])
    expect(within(rows[0]).getByText('1 application prepared')).toBeInTheDocument()
    expect(within(rows[1]).getByText('110 postings scored')).toBeInTheDocument()
    // the features within an activity, only when there are several
    expect(within(rows[0]).getByText('Tailoring the CV and letter')).toBeInTheDocument()
    expect(within(rows[1]).queryByText('Scoring postings')).toBeNull()
  })

  it('says how full the plan window is and the room left', async () => {
    mockDoor({ status_summary: summary({ cost: COST, plan: PLAN }) })
    render(<Analytics />)
    expect(await screen.findByText(/42% of this 5-hour window used/)).toBeInTheDocument()
    expect(screen.getByText(/room for about 6 searches or 2 prepared applications/)).toBeInTheDocument()
  })

  it('before any call: one quiet line', async () => {
    mockDoor({ status_summary: summary({ cost: null, plan: null }) })
    render(<Analytics />)
    expect(await screen.findByText(/shows here after your first search/)).toBeInTheDocument()
  })
})
