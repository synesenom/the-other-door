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

const DAY = 86_400_000

/** "today", "yesterday", "4 days ago", "2 weeks ago", else the date; null when there is no readable time. */
export function whenText(iso: string | null | undefined, now: Date = new Date()): string | null {
  if (!iso) return null
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return null
  const start = (d: Date) => Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate())
  const days = Math.round((start(now) - start(then)) / DAY)
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 7) return `${days} days ago`
  if (days < 28) {
    const weeks = Math.floor(days / 7)
    return weeks === 1 ? '1 week ago' : `${weeks} weeks ago`
  }
  return then.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

const ENDED: Record<string, string> = { rejected: 'rejected', ghosted: 'ghosted', discarded: 'withdrawn' }

/** Under a card's title and company: the interview rounds as dots (passed, or the one now) and a few words. */
export function cardNote(m: Match, now: Date = new Date()): { dots: ('passed' | 'pending')[]; text: string | null } {
  const rounds = m.rounds ?? []
  const dots = rounds.filter((r) => r.result === 'passed' || r.result === 'pending').map((r) => r.result as 'passed' | 'pending')
  if (m.status in ENDED) return { dots: [], text: ENDED[m.status]! }
  if (m.status === 'offer') return { dots, text: 'offer' }
  if (m.status.startsWith('interview:')) return { dots, text: rounds[rounds.length - 1]?.stage ?? m.status.slice('interview:'.length) }
  return { dots: [], text: whenText(m.updated_at, now) }
}
