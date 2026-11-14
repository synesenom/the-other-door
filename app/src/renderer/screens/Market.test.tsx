// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
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
  companies: {
    population: 'scraped',
    rows: [
      { name: 'Trustpilot', count: 7, followed: false },
      { name: 'Lunar', count: 5, followed: true },
    ],
  },
  warning: 'Some skill names were left as written.',
  report_path: null,
}

function show(handlers: Record<string, unknown> = {}) {
  const h = mockDoor(handlers)
  render(<Market />)
  return h
}

describe('Market', () => {
  it('counts once on mount, unsaved, and shows the counts and top skills only', async () => {
    const { call } = show({ market: MARKET })
    expect(call).toHaveBeenCalledWith('market', { save: false })
    const section = screen.getByRole('region', { name: 'Market' })
    expect(await within(section).findByText('412 ads read, 120 scored, 18 at your minimum score.')).toBeInTheDocument()
    expect(within(section).getByRole('listitem', { name: 'SQL' })).toHaveTextContent('in your CV')
    expect(within(section).getByRole('listitem', { name: 'dbt' })).toHaveTextContent('not in your CV')
    expect(screen.queryByRole('button', { name: /Make a plan/ })).toBeNull()
    expect(screen.queryByText(/Python/)).toBeNull()
    expect(screen.queryByText(/left as written/)).toBeNull()
    expect(call.mock.calls.filter((c) => c[0] === 'market')).toHaveLength(1)
  })

  it('a failed report says why', async () => {
    show({ market: () => { throw { message: 'companies.json: invalid JSON' } } })
    expect(await screen.findByRole('alert')).toHaveTextContent('companies.json: invalid JSON')
  })

  it('titles no keyword covers are added to the search only after a yes', async () => {
    const { call } = show({
      market: MARKET,
      show_profile: { config: { search_keywords: ['Data Analyst'], role_targets: ['Data Analyst'] } },
      init_profile: { config_path: '/x' },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Add these titles to my search' }))
    expect(call.mock.calls.map((c) => c[0])).not.toContain('init_profile')
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('Analytics Engineer')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(call.mock.calls.map((c) => c[0])).not.toContain('init_profile')
    await userEvent.click(screen.getByRole('button', { name: 'Add these titles to my search' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Add' }))
    expect(call).toHaveBeenCalledWith('init_profile', { search_keywords: ['Data Analyst', 'Analytics Engineer'] })
    expect(await screen.findByText('Added to your search keywords.')).toBeInTheDocument()
  })

  it('with no search keywords the titles go after the role targets; a failed save says why', async () => {
    const { call } = show({
      market: MARKET,
      show_profile: { config: { role_targets: ['Data Analyst'] } },
      init_profile: () => { throw { message: 'the ledgers are busy' } },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Add these titles to my search' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Add' }))
    expect(call).toHaveBeenCalledWith('init_profile', { search_keywords: ['Data Analyst', 'Analytics Engineer'] })
    expect(await screen.findByText('the ledgers are busy')).toBeInTheDocument()
  })

  it('an employer not followed gets a Follow button; a followed one none', async () => {
    const { call } = show({
      market: MARKET,
      add_company: { dry_run: false, results: [{ input: 'Trustpilot', name: 'Trustpilot', status: 'followed', reason: null }] },
    })
    expect(screen.queryByRole('button', { name: 'Follow Lunar' })).toBeNull()
    await userEvent.click(await screen.findByRole('button', { name: 'Follow Trustpilot' }))
    expect(screen.queryByRole('button', { name: 'Follow Lunar' })).toBeNull()
    expect(call).toHaveBeenCalledWith('add_company', { inputs: ['Trustpilot'] })
    await waitFor(() => expect(screen.getByRole('listitem', { name: 'Trustpilot' })).toHaveTextContent('followed'))
    expect(screen.queryByRole('button', { name: 'Follow Trustpilot' })).toBeNull()
    expect(call.mock.calls.filter((c) => c[0] === 'market')).toHaveLength(1)
  })

  it('a feed that cannot be followed says the reason; a failed call says why', async () => {
    show({
      market: MARKET,
      add_company: { results: [{ input: 'Trustpilot', name: 'Trustpilot', status: 'unresolved', reason: 'no feed found' }] },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Follow Trustpilot' }))
    expect(await screen.findByText('no feed found')).toBeInTheDocument()
    cleanup()
    show({ market: MARKET, add_company: () => { throw { message: 'busy now' } } })
    await userEvent.click(await screen.findByRole('button', { name: 'Follow Trustpilot' }))
    expect(await screen.findByText('busy now')).toBeInTheDocument()
  })
})
