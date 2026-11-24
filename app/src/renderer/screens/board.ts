// The applications board, pure: its five columns, and what a card says under its title and company.
import type { Match } from '../api'

export interface BoardColumn {
  heading: string
  rows: Match[]
}

const COLUMNS: { heading: string; has: (status: string) => boolean }[] = [
  { heading: 'Prepared', has: (s) => s === 'prepared' },
  { heading: 'Applied', has: (s) => s === 'applied' },
  { heading: 'Interviewing', has: (s) => s.startsWith('interview:') },
  { heading: 'Offer', has: (s) => s === 'offer' },
]

const newest = (a: Match, b: Match) => (b.updated_at ?? '').localeCompare(a.updated_at ?? '')

/** Prepared, Applied, Interviewing, Offer from the jobs in play, and Closed from the ones that ended; newest first. */
export function boardColumns(ongoing: Match[], closed: Match[]): BoardColumn[] {
  return [
    ...COLUMNS.map((c) => ({ heading: c.heading, rows: ongoing.filter((m) => c.has(m.status)).sort(newest) })),
    { heading: 'Closed', rows: [...closed].sort(newest) },
  ]
}

const ENDED: Record<string, string> = { rejected: 'rejected', ghosted: 'ghosted', discarded: 'withdrawn' }

/** Under a card's title and company: a dot per interview round passed, and a few words (the round, or how it ended). */
export function cardNote(m: Match): { passed: number; text: string | null } {
  const rounds = m.rounds ?? []
  const passed = rounds.filter((r) => r.result === 'passed').length
  if (m.status in ENDED) return { passed: 0, text: ENDED[m.status]! }
  if (m.status === 'offer') return { passed, text: 'offer' }
  if (m.status.startsWith('interview:')) return { passed, text: rounds[rounds.length - 1]?.stage ?? m.status.slice('interview:'.length) }
  return { passed: 0, text: null }
}

/** The words of a card's warning, when the server says its stage has been quiet too long; else null. */
export function stalledText(m: Match): string | null {
  if (!m.stalled_days) return null
  return `${m.status === 'prepared' ? 'Not sent' : 'No answer'} in ${m.stalled_days} days`
}
