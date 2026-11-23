// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
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
  companies: { population: 'scraped', rows: [{ name: 'Trustpilot', count: 7, followed: false }] },
  warning: 'Some skill names were left as written.',
  report_path: null,
}

function show(handlers: Record<string, unknown> = {}, onOpenCv?: () => void) {
  const h = mockDoor(handlers)
  render(<Market onOpenCv={onOpenCv} />)
  return h
}

describe('Market', () => {
  it('counts once on mount, unsaved, and lists the top skills with their share, checked when the CV has them', async () => {
    const { call } = show({ market: MARKET })
    expect(call).toHaveBeenCalledWith('market', { save: false })
    const section = screen.getByRole('region', { name: 'Market' })
    const sql = await within(section).findByRole('listitem', { name: 'SQL, in your CV' })
    expect(sql).toHaveTextContent('50% of the ads')
    expect(sql).toHaveClass('skill-fits')
    const dbt = within(section).getByRole('listitem', { name: 'dbt, not in your CV' })
    expect(dbt).toHaveTextContent('25% of the ads')
    expect(dbt).toHaveClass('skill-gap')
    expect(within(section).getAllByRole('listitem')).toHaveLength(3)
    expect(section).not.toHaveTextContent(/Analytics Engineer|Trustpilot|Python|left as written/)
    expect(call.mock.calls.map((c) => c[0])).toEqual(['market'])
  })

  it('a failed count is said nowhere: nothing the user can fix (principle 9)', async () => {
    show({ market: () => { throw { message: 'companies.json: invalid JSON' } } })
    await waitFor(() => expect(screen.queryByText(/Counting the ads/)).toBeNull())
    expect(screen.queryByRole('alert')).toBeNull()
    expect(document.body).not.toHaveTextContent('invalid JSON')
  })

  it('a skill the CV lacks leads to the CV: one button under the list, in the plural for several', async () => {
    const onOpenCv = vi.fn()
    show({ market: MARKET }, onOpenCv)
    const button = await screen.findByRole('button', { name: 'Add the missing skills to your CV' })
    expect(button).toHaveClass('secondary')
    await userEvent.click(button)
    expect(onOpenCv).toHaveBeenCalledTimes(1)
  })

  it('one missing skill: the singular; none missing: no button', async () => {
    show({ market: { ...MARKET, skills: MARKET.skills.slice(0, 2) } }, vi.fn())
    expect(await screen.findByRole('button', { name: 'Add the missing skill to your CV' })).toBeInTheDocument()
    cleanup()
    show({ market: { ...MARKET, skills: MARKET.skills.slice(0, 1) } }, vi.fn())
    await screen.findByRole('listitem', { name: 'SQL, in your CV' })
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('with no ads read it says when the market shows', async () => {
    show({ market: { ...MARKET, counts: { scraped: 0, scored: 0, above_min_score: 0 }, skills: [] } })
    expect(await screen.findByText('The market shows here once ads are read.')).toBeInTheDocument()
    expect(screen.queryByRole('list')).toBeNull()
  })
})
