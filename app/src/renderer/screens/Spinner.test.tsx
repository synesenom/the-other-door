// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { Spinner } from './Spinner'
import { Matches } from './Matches'
import { match, matchesResult, mockDoor, summary } from '../testing'

afterEach(cleanup)

describe('Spinner', () => {
  it('is a status that shows the message and nothing else', () => {
    const { container } = render(<Spinner message="Scoring 12 of 40" />)
    expect(screen.getByRole('status')).toHaveTextContent('Scoring 12 of 40')
    expect(container.textContent).toBe('Scoring 12 of 40')
  })

  it('shows in Matches while a run is in progress, in words: never its raw message or its pid', async () => {
    mockDoor({
      status_summary: summary({
        in_progress: { purpose: 'run', pid: 4242, started_at: 'x', message: 'Searching jobindex', done: 1, total: 5, site: 'jobindex', stage: 'keyword', updated_at: 'y' },
      }),
      list_matches: matchesResult([match()]),
      show: { id: 'jobindex.1', title: 'T', company: 'C', status: 'unapplied' },
    })
    const { container } = render(<Matches />)
    await screen.findByText('Finding new jobs…')
    expect(screen.getAllByRole('status').some((s) => s.textContent === 'Finding new jobs…')).toBe(true)
    expect(container.textContent).not.toMatch(/Searching jobindex/)
    expect(container.textContent).not.toMatch(/4242/)
  })

  it('has no spinner when nothing runs', async () => {
    mockDoor({ status_summary: summary(), list_matches: matchesResult([match()]), show: { id: 'jobindex.1', title: 'T', company: 'C', status: 'unapplied' } })
    render(<Matches />)
    await screen.findAllByRole('listitem')
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('the stylesheet turns animation off for reduced motion', () => {
    const css = readFileSync(join(__dirname, '..', 'styles.css'), 'utf8')
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[^{]*\{[^}]*\.spinner[^}]*\{[^}]*animation:\s*none/s)
  })
})
