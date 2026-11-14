// What is wrong and needs the user, for the short lines at the foot of the sidebar: the data folders, Claude, the CV,
// Google Drive, something that keeps going wrong, in that order, each with where it is fixed. A site a run
// could not read once is not here: the user can do nothing about it but run again (docs/design/README.md,
// principle 9). The same failure run after run is (status_summary's `recurring_problem`, door.core.recurring):
// the user can send a report, and the line goes once one is saved or the failure stops. Pure.
import { attention, type DriveStatus } from './connection-rows'
import type { DoctorReport } from './onboarding/reducer'

export interface Problem {
  key: string
  text: string
  /** Where it is fixed: Settings, or Profile on the CV. */
  target: 'settings' | 'settings-report' | 'profile-cv' | 'profile'
}

export interface ProblemInput {
  doctor: DoctorReport | null
  drive: DriveStatus | null
  cv: { exists: boolean } | null
  /** status_summary's `recurring_problem`; null while unknown (and on the phone). */
  recurring: boolean | null
  /** A sync found both this computer and Drive changed: which to keep is the user's. */
  driveConflict?: boolean
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
  // the example CV needs no line: a run refuses it and says why
  if (input.cv && !input.cv.exists) out.push({ key: 'cv', text: 'You have no CV yet', target: 'profile-cv' })
  if (input.drive?.connected && input.driveConflict) out.push({ key: 'drive', text: 'Google Drive needs a choice', target: 'settings' })
  else if (input.drive?.connected && input.drive.last_error) out.push({ key: 'drive', text: 'Google Drive sync failed', target: 'settings' })
  if (input.recurring) out.push({ key: 'report', text: 'Something keeps going wrong. Send a report', target: 'settings-report' })
  return out
}
