/** Two days with no run and the list is no longer fresh: boards post every day. */
export const STALE_DAYS = 2

/**
 * How fresh the matches are, from the last run's end: `last` for the Find button's tooltip ("Last run 2 h ago"),
 * `stale` for the warning beside it, null while a run is recent.
 */
export function runFreshness(finishedAt: string | null | undefined, now = new Date()): { last: string | null; stale: string | null } {
  const t = finishedAt ? new Date(finishedAt).getTime() : NaN
  if (Number.isNaN(t)) return { last: null, stale: 'Not run yet' }
  const hours = Math.max(0, (now.getTime() - t) / 3_600_000)
  const days = Math.floor(hours / 24)
  const when = hours < 1 ? 'just now' : days === 0 ? `${Math.floor(hours)} h ago` : days === 1 ? 'yesterday' : `${days} days ago`
  return { last: `Last run ${when}`, stale: days >= STALE_DAYS ? `No run in ${days} days` : null }
}
