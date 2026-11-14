// What is wrong and needs the user, for the short lines at the foot of the sidebar: the data folders, Claude, the CV,
// the Claude plan's window when it is nearly full (waited out: it opens nothing), Google Drive, something that keeps going wrong,
// in that order, each with where it is fixed. A site a run
// could not read once is not here: the user can do nothing about it but run again (docs/design/README.md,
// principle 9). The same failure run after run is (status_summary's `recurring_problem`, door.core.recurring):
// the user can send a report, and the line goes once one is saved or the failure stops. Pure.
import { attention, type DriveStatus } from './connection-rows'
import type { PlanBlock } from '../api'
import type { DoctorReport } from './onboarding/reducer'

export interface Problem {
  key: string
  text: string
  /** Where it is fixed: Settings, or Profile on the CV; `none` has nothing to fix (the plan's window), said, not a button. */
  target: 'settings' | 'settings-report' | 'profile-cv' | 'profile' | 'none'
}

export interface ProblemInput {
  doctor: DoctorReport | null
  drive: DriveStatus | null
  cv: { exists: boolean } | null
  /** status_summary's `recurring_problem`; null while unknown (and on the phone). */
  recurring: boolean | null
  /** A sync found both this computer and Drive changed: which to keep is the user's. */
  driveConflict?: boolean
  /** status_summary's `plan`; null or missing while unknown. */
  plan?: PlanBlock | null
  /** The clock, for the reset time; now by default. */
  now?: Date
}

/** As the CLI: room for this many prepares or fewer is worth saying (`common._PREPARE_ROOM_SHORT`). */
export const PREPARE_ROOM_SHORT = 3

const pad = (n: number) => String(n).padStart(2, '0')

/** "15:30" for a time today, "Mon 15:30" for another day, in local time. */
function clock(date: Date, now: Date): string {
  const hm = `${pad(date.getHours())}:${pad(date.getMinutes())}`
  if (date.toDateString() === now.toDateString()) return hm
  return `${date.toLocaleDateString('en-US', { weekday: 'short' })} ${hm}`
}

/** When the plan's window resets (the binding one, else the first with figures), or null when unknown. */
export function planReset(plan: PlanBlock | null | undefined): Date | null {
  if (!plan) return null
  const window = (plan.binding && plan[plan.binding] ? plan[plan.binding] : undefined) ?? plan.five_hour ?? plan.seven_day
  const reset = (window as { resets_at?: string } | undefined)?.resets_at
  const date = reset ? new Date(reset) : null
  return date && !Number.isNaN(date.getTime()) ? date : null
}

/** The line for a plan that needs the user, or null: limit reached, a warning, or room for few prepares. A window
 * whose reset has passed says nothing (as `usage.latest` drops it). Pure. */
export function planLine(plan: PlanBlock | null | undefined, now: Date = new Date()): string | null {
  if (!plan) return null
  const date = planReset(plan)
  if (date && date.getTime() <= now.getTime()) return null
  const resets = date ? `, resets ${clock(date, now)}` : ''
  if (plan.status === 'rejected') return `${plan.warning || "Claude's usage limit is reached"}${resets}`
  const room = plan.room?.prepare
  if (room != null && (room <= PREPARE_ROOM_SHORT || plan.warning)) {
    return `Claude can prepare ${room} more${resets}`
  }
  return plan.warning ? `${plan.warning}${resets}` : null
}

export function problems(input: ProblemInput): Problem[] {
  const out: Problem[] = []
  // Data that could not be upgraded, or was written by a newer version or an older major: every tool refuses until it is dealt with,
  // so this line comes first (a busy folder, held by a run for a moment, says nothing: the next call retries it)
  const data = input.doctor?.data
  if (data?.state === 'failed') out.push({ key: 'data', text: 'Your data could not be upgraded. Send a report', target: 'settings-report' })
  else if (data?.state === 'newer') out.push({ key: 'data', text: 'Install the latest version of The other door', target: 'settings' })
  else if (data?.state === 'old_major') out.push({ key: 'data', text: 'Your data is from an older version of The other door', target: 'settings' })
  const claude = attention(input.doctor, null)
  if (claude) out.push({ key: 'claude', text: claude, target: 'settings' })
  const plan = planLine(input.plan, input.now)
  if (plan) out.push({ key: 'plan', text: plan, target: 'none' })
  // the example CV needs no line: a run refuses it and says why
  if (input.cv && !input.cv.exists) out.push({ key: 'cv', text: 'You have no CV yet', target: 'profile-cv' })
  if (input.drive?.connected && input.driveConflict) out.push({ key: 'drive', text: 'Google Drive needs a choice', target: 'settings' })
  else if (input.drive?.connected && input.drive.last_error) out.push({ key: 'drive', text: 'Google Drive sync failed', target: 'settings' })
  if (input.recurring) out.push({ key: 'report', text: 'Something keeps going wrong. Send a report', target: 'settings-report' })
  return out
}
