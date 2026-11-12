import { STATUSES } from '../api'

/** One line on what a status change did, in words. */
export function statusNotice(status: string, title: string): string {
  if (status === 'unapplied') return 'Back in Matches.'
  const word = status.startsWith('interview:') ? 'Interview' : (STATUSES.find((s) => s.value === status)?.word ?? status)
  const inPlay = ['prepared', 'applied', 'offer'].includes(status) || status.startsWith('interview:')
  return inPlay ? `${word}: ${title}. It is in Applications now.` : `${word}: ${title}.`
}
