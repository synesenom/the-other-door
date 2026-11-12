// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../testing'
import { Market } from './Market'

afterEach(cleanup)

const MARKET = {
  window: { days: 30 },
  counts: { scraped: 412, scored: 120, above_min_score: 18 },
  skills: [
    { name: 'SQL', count: 60, share: 0.5, have: true, trend: null },
    { name: 'dbt', count: 30, share: 0.25, have: false, trend: null },
    { name: 'Power BI', count: 24, share: 0.2, have: false, trend: null },
  ],
  near_misses: { n: 9, rows: [{ skill: 'Python', count: 5 }] },
  uncovered_titles: [{ title: 'Analytics Engineer', count: 4 }],
  companies: { population: 'scraped', rows: [] },
  warning: null,
  report_path: null,
}

function show(handlers: Record<string, unknown> = {}) {
  const h = mockDoor(handlers)
  const onPlan = vi.fn()
  const onSearchChanged = vi.fn()
  render(<Market onPlan={onPlan} onSearchChanged={onSearchChanged} />)
  return { ...h, onPlan, onSearchChanged }
}

describe('Market', () => {
  it('runs only when opened, unsaved, and says the Claude call first', async () => {
    const { call } = show({ market: MARKET })
    expect(screen.getByText(/one short Claude call/)).toBeInTheDocument()
    expect(call).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'What the ads asked for this month' }))
    expect(call).toHaveBeenCalledWith('market', { save: false })
    const section = screen.getByRole('region', { name: 'What the ads asked for this month' })
    expect(await within(section).findByText('412 ads read, 120 scored, 18 at your minimum score.')).toBeInTheDocument()
    expect(within(section).getByRole('listitem', { name: 'SQL' })).toHaveTextContent('in your CV')
    expect(within(section).getByRole('listitem', { name: 'dbt' })).toHaveTextContent('not in your CV')
    expect(within(section).getByText(/Python/)).toBeInTheDocument()
  })

  it('a report that failed is asked again when reopened', async () => {
    let calls = 0
    show({
      market: () => {
        if (calls++ === 0) throw { message: 'companies.json: invalid JSON' }
        return MARKET
      },
    })
    const fold = screen.getByRole('button', { name: 'What the ads asked for this month' })
    await userEvent.click(fold)
    expect(await screen.findByRole('alert')).toHaveTextContent('companies.json: invalid JSON')
    await userEvent.click(fold)
    await userEvent.click(fold)
    expect(await screen.findByText('412 ads read, 120 scored, 18 at your minimum score.')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('a plan for the skills you lack is handed on', async () => {
    const { onPlan } = show({ market: MARKET })
    await userEvent.click(screen.getByRole('button', { name: 'What the ads asked for this month' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Make a plan for dbt and Power BI' }))
    expect(onPlan).toHaveBeenCalledWith(['dbt', 'Power BI'])
  })

  it('titles no keyword covers are added to the search only after a yes', async () => {
    const { call, onSearchChanged } = show({
      market: MARKET,
      show_profile: { config: { search_keywords: ['Data Analyst'], role_targets: ['Data Analyst'] } },
      init_profile: { config_path: '/x' },
    })
    await userEvent.click(screen.getByRole('button', { name: 'What the ads asked for this month' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Add these titles to my search' }))
    expect(call.mock.calls.map((c) => c[0])).not.toContain('init_profile')
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('Analytics Engineer')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add' }))
    expect(call).toHaveBeenCalledWith('init_profile', { search_keywords: ['Data Analyst', 'Analytics Engineer'] })
    expect(await screen.findByText('Added to your search keywords.')).toBeInTheDocument()
    expect(onSearchChanged).toHaveBeenCalled() // so the details shown elsewhere are read again
  })

  it('with no search keywords the titles go after the role targets; a failed save says why', async () => {
    const { call } = show({
      market: { ...MARKET, warning: 'Some skill names were left as written.' },
      show_profile: { config: { role_targets: ['Data Analyst'] } },
      init_profile: () => { throw { message: 'the ledgers are busy' } },
    })
    await userEvent.click(screen.getByRole('button', { name: 'What the ads asked for this month' }))
    expect(await screen.findByText('Some skill names were left as written.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Add these titles to my search' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Add' }))
    expect(call).toHaveBeenCalledWith('init_profile', { search_keywords: ['Data Analyst', 'Analytics Engineer'] })
    expect(await screen.findByText('the ledgers are busy')).toBeInTheDocument()
  })
})
