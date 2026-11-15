import { describe, expect, it } from 'vitest'
import { boardColumns, cardNote, whenText } from './board'
import { match } from '../testing'

const NOW = new Date('2026-10-30T12:00:00Z')

describe('whenText', () => {
  it('today, yesterday, days, weeks, then the date', () => {
    expect(whenText('2026-10-30T08:00:00Z', NOW)).toBe('today')
    expect(whenText('2026-10-29T20:00:00Z', NOW)).toBe('yesterday')
    expect(whenText('2026-10-26T12:00:00Z', NOW)).toBe('4 days ago')
    expect(whenText('2026-10-22T12:00:00Z', NOW)).toBe('1 week ago')
    expect(whenText('2026-10-10T12:00:00Z', NOW)).toBe('2 weeks ago')
    expect(whenText('2026-08-01T12:00:00Z', NOW)).toMatch(/Aug/)
    expect(whenText(null, NOW)).toBeNull()
    expect(whenText('soon', NOW)).toBeNull()
  })
})

describe('boardColumns', () => {
  it('five columns in order, each with its jobs; Closed from the closed list', () => {
    const ongoing = [
      match({ id: 'a', status: 'offer' }),
      match({ id: 'b', status: 'applied' }),
      match({ id: 'c', status: 'interview:technical' }),
      match({ id: 'd', status: 'prepared' }),
    ]
    const closed = [match({ id: 'e', status: 'rejected' })]
    const cols = boardColumns(ongoing as never, closed as never)
    expect(cols.map((c) => c.heading)).toEqual(['Prepared', 'Applied', 'Interviewing', 'Offer', 'Closed'])
    expect(cols.map((c) => c.rows.map((r) => r.id))).toEqual([['d'], ['b'], ['c'], ['a'], ['e']])
  })

  it('the most recently changed first in each column', () => {
    const cols = boardColumns(
      [match({ id: 'old', status: 'applied', updated_at: '2026-10-01T00:00:00Z' }), match({ id: 'new', status: 'applied', updated_at: '2026-10-20T00:00:00Z' })] as never,
      [],
    )
    expect(cols[1]!.rows.map((r) => r.id)).toEqual(['new', 'old'])
  })
})

describe('cardNote', () => {
  it('prepared and applied: when it moved', () => {
    expect(cardNote(match({ status: 'applied', updated_at: '2026-10-26T12:00:00Z' }) as never, NOW)).toEqual({ dots: [], text: '4 days ago' })
  })

  it('interviewing: a dot per round (passed or next) and the round now', () => {
    const m = match({ status: 'interview:technical', rounds: [{ stage: 'screening', result: 'passed' }, { stage: 'technical', result: 'pending' }] })
    expect(cardNote(m as never, NOW)).toEqual({ dots: ['passed', 'pending'], text: 'technical' })
  })

  it('applied and silent: says no answer, with the days the server sent', () => {
    const m = match({ status: 'applied', updated_at: '2026-09-01T12:00:00Z', no_answer: true, no_answer_days: 30 })
    expect(cardNote(m as never, NOW)).toEqual({ dots: [], text: 'No answer in 30 days' })
    expect(cardNote({ ...m, no_answer_days: 45 } as never, NOW).text).toBe('No answer in 45 days')
    expect(cardNote({ ...m, no_answer: false } as never, NOW).text).toMatch(/Sep|weeks/)
    expect(cardNote(match({ status: 'applied', updated_at: '2026-10-26T12:00:00Z' }) as never, NOW).text).toBe('4 days ago')
  })

  it('interviewing and silent: the dots and the round stay, then the silence', () => {
    const rounds = [{ stage: 'screening', result: 'passed' }, { stage: 'technical', result: 'pending' }]
    const m = match({ status: 'interview:technical', rounds, no_answer: true, no_answer_days: 30 })
    expect(cardNote(m as never, NOW)).toEqual({ dots: ['passed', 'pending'], text: 'technical · no answer in 30 days' })
    expect(cardNote({ ...m, no_answer: false } as never, NOW).text).toBe('technical')
  })

  it('offer, closed and prepared ignore the flag', () => {
    for (const status of ['offer', 'rejected', 'ghosted', 'discarded']) {
      expect(cardNote(match({ status, no_answer: true, no_answer_days: 30 }) as never, NOW).text).not.toMatch(/answer/i)
    }
    expect(cardNote(match({ status: 'prepared', updated_at: '2026-10-26T12:00:00Z', no_answer: true, no_answer_days: 30 }) as never, NOW).text).toBe('4 days ago')
  })

  it('offer: the rounds passed, then the word', () => {
    const m = match({ status: 'offer', rounds: [{ stage: 'screening', result: 'passed' }] })
    expect(cardNote(m as never, NOW)).toEqual({ dots: ['passed'], text: 'offer' })
  })

  it('closed: how it ended', () => {
    expect(cardNote(match({ status: 'rejected' }) as never, NOW).text).toBe('rejected')
    expect(cardNote(match({ status: 'ghosted' }) as never, NOW).text).toBe('ghosted')
    expect(cardNote(match({ status: 'discarded' }) as never, NOW).text).toBe('withdrawn')
  })
})
