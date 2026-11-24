import { describe, expect, it } from 'vitest'
import { boardColumns, cardNote, stalledText } from './board'
import { match } from '../testing'

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
  it('prepared and applied: nothing under the company', () => {
    expect(cardNote(match({ status: 'applied', updated_at: '2026-10-26T12:00:00Z' }) as never)).toEqual({ passed: 0, text: null })
    expect(cardNote(match({ status: 'prepared' }) as never)).toEqual({ passed: 0, text: null })
  })

  it('interviewing: a dot per round passed and the round now', () => {
    const m = match({ status: 'interview:technical', rounds: [{ stage: 'screening', result: 'passed' }, { stage: 'technical', result: 'pending' }] })
    expect(cardNote(m as never)).toEqual({ passed: 1, text: 'technical' })
  })

  it('offer: the rounds passed, then the word', () => {
    const m = match({ status: 'offer', rounds: [{ stage: 'screening', result: 'passed' }] })
    expect(cardNote(m as never)).toEqual({ passed: 1, text: 'offer' })
  })

  it('closed: how it ended', () => {
    expect(cardNote(match({ status: 'rejected' }) as never).text).toBe('rejected')
    expect(cardNote(match({ status: 'ghosted' }) as never).text).toBe('ghosted')
    expect(cardNote(match({ status: 'discarded' }) as never).text).toBe('withdrawn')
  })
})

describe('stalledText', () => {
  it('says what has not happened, in the days the server sent', () => {
    expect(stalledText(match({ status: 'prepared', stalled_days: 14 }) as never)).toBe('Not sent in 14 days')
    expect(stalledText(match({ status: 'applied', stalled_days: 45 }) as never)).toBe('No answer in 45 days')
    expect(stalledText(match({ status: 'interview:technical', stalled_days: 21 }) as never)).toBe('No answer in 21 days')
  })

  it('nothing when the server says the card is not stalled', () => {
    expect(stalledText(match({ status: 'applied', stalled_days: null }) as never)).toBeNull()
    expect(stalledText(match({ status: 'applied' }) as never)).toBeNull()
  })
})
