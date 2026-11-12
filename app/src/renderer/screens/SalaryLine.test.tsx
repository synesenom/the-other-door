// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { SalaryLine } from './SalaryLine'
import { mockDoor } from '../testing'
import type { Salary } from '../api'

afterEach(cleanup)

const salary: Salary = {
  low: 55000,
  high: 70000,
  currency: 'DKK',
  period: 'month',
  gross: true,
  position: 'within',
  basis: 'Ten years against the five asked.',
  sources: [
    { title: 'Salary statistics', url: 'https://example.com/stats' },
    { title: 'Union survey', url: 'https://example.org/survey' },
  ],
  ad_salary: null,
  as_of: '2026-11-07T10:00:00+00:00',
}

describe('SalaryLine', () => {
  it('shows the range, its period and its sources as links', async () => {
    const door = mockDoor({})
    render(<SalaryLine salary={salary} />)
    expect(screen.getByText('55,000–70,000 DKK a month, gross')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Union survey' }))
    expect(door.openExternal).toHaveBeenCalledWith('https://example.org/survey')
  })

  it('says it is an estimate, and why, behind the info icon', () => {
    mockDoor({})
    render(<SalaryLine salary={salary} />)
    expect(screen.getByRole('button', { name: 'About this estimate' })).toBeInTheDocument()
  })

  it('names the ad’s own figure when it states one', () => {
    mockDoor({})
    render(<SalaryLine salary={{ ...salary, low: 60000, high: 60000, ad_salary: 'DKK 60,000 per month' }} />)
    expect(screen.getByText('60,000 DKK a month, gross')).toBeInTheDocument()
    expect(screen.getByText(/the ad says DKK 60,000 per month/i)).toBeInTheDocument()
  })

  it('shows nothing without an estimate', () => {
    mockDoor({})
    const { container } = render(<SalaryLine salary={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})
