// A run started from a terminal or Claude Code, seen on the run board, announced when it ends.
import { noticeFor, type Notice } from './notices'
import type { RunBoard } from './run-board'

/** The start of the run that was somebody else's and is over; null for any other change of board. */
export function foreignRunEnded(prev: RunBoard, next: RunBoard): { startedAt: string } | null {
  if (!prev.active || prev.own || prev.demo || next.active) return null
  return { startedAt: prev.started_at }
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

/** Returns the board listener: it notices the ending and reads the run's record from `status_summary`. */
export function watchForeignEnd(
  server: { call(tool: string, args: Record<string, unknown>): Promise<unknown> },
  notify: (notice: Notice) => void,
): (board: RunBoard) => Promise<void> {
  let prev: RunBoard = { active: false }
  return async (next) => {
    const ended = foreignRunEnded(prev, next)
    prev = next
    if (!ended) return
    let lastRun: { started_at?: string; new_above_threshold?: number } | null = null
    try {
      const summary = await server.call('status_summary', {})
      const review = isObject(summary) ? summary['since_last_review'] : null
      const run = isObject(review) ? review['last_run'] : null
      if (isObject(run)) {
        lastRun = {
          ...(typeof run['started_at'] === 'string' ? { started_at: run['started_at'] } : {}),
          ...(typeof run['new_above_threshold'] === 'number' ? { new_above_threshold: run['new_above_threshold'] } : {}),
        }
      }
    } catch {
      // the record is a bonus: the notice is plainer without it
    }
    try {
      const notice = noticeFor({ kind: 'foreign-run-ended', startedAt: ended.startedAt, lastRun })
      if (notice) notify(notice)
    } catch {
      // never fatal
    }
  }
}
