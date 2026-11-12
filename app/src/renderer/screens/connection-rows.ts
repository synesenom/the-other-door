// What Settings' Connections list says about Claude and Google Drive, and when the sidebar should
// say something: pure functions of doctor's report and status_summary's `drive` block.
import type { DoctorReport } from './onboarding/reducer'

/** `status_summary.drive` (never the tokens). `configured` is false in a build without the Google client. */
export interface DriveStatus {
  connected: boolean
  account: string | null
  last_synced: string | null
  last_error: string | null
  configured?: boolean
}

/** Where the app runs: the user's data, or the made-up data of the demo or the onboarding sandbox. */
export type Where = 'real' | 'demo' | 'sandbox'

export type ClaudeRow =
  | { kind: 'checking' }
  | { kind: 'not-installed' }
  | { kind: 'signed-in'; email?: string; plan?: string }
  | { kind: 'signed-out' }
  | { kind: 'api-key' }
  | { kind: 'unknown' }

export type DriveRow =
  | { kind: 'checking' }
  | { kind: 'unavailable'; why: string }
  | { kind: 'off' }
  | { kind: 'connected'; account: string | null; lastSynced: string | null; error: string | null }

const PLANS: Record<string, string> = { max: 'Max', pro: 'Pro', team: 'Team', enterprise: 'Enterprise' }

export function claudeRow(doctor: DoctorReport | null): ClaudeRow {
  if (doctor === null) return { kind: 'checking' }
  if (doctor.error) return { kind: 'unknown' }
  if (!Array.isArray(doctor.checks)) return { kind: 'unknown' }
  const cli = doctor.checks.find((c) => c.name === 'claude CLI')
  if (cli && cli.status !== 'ok') return { kind: 'not-installed' }
  const login = doctor.checks.find((c) => c.name === 'claude login')
  const details = login?.details
  if (!login || !details) return { kind: 'unknown' }
  if (login.status === 'ok') {
    const email = typeof details['email'] === 'string' ? details['email'] : undefined
    const sub = typeof details['subscriptionType'] === 'string' ? details['subscriptionType'] : undefined
    return { kind: 'signed-in', ...(email ? { email } : {}), ...(sub ? { plan: PLANS[sub.toLowerCase()] ?? sub } : {}) }
  }
  const method = String(details['authMethod'] ?? '').toLowerCase()
  if (details['loggedIn'] === true && method.includes('api') && method.includes('key')) return { kind: 'api-key' }
  return { kind: 'signed-out' }
}

export function driveRow(drive: DriveStatus | null, where: Where): DriveRow {
  if (where === 'demo') return { kind: 'unavailable', why: 'Not available in the demo' }
  if (where === 'sandbox') return { kind: 'unavailable', why: 'Not available in the onboarding sandbox' }
  if (drive === null) return { kind: 'checking' }
  if (drive.configured === false) return { kind: 'unavailable', why: 'Not available in this build' }
  if (!drive.connected) return { kind: 'off' }
  return { kind: 'connected', account: drive.account, lastSynced: drive.last_synced, error: drive.last_error }
}

/** What `setup` answers about its installs (its `outcome` also counts what else the home lacks, a sign-in say, so it is not read). */
export interface SetupAnswer {
  results?: { tool: string; ok: boolean; error?: string }[]
}

/** Why an install failed, from the installers' own errors, or null when every install worked. */
export function installFailure(r: SetupAnswer): string | null {
  const failed = (r.results ?? []).filter((s) => !s.ok)
  return failed.length ? failed.map((s) => s.error || 'The install did not finish.').join(' ') : null
}

/** The sidebar's line when a connection needs the user, or null: never for a Drive that is simply off. */
export function attention(doctor: DoctorReport | null, drive: DriveStatus | null): string | null {
  const claude = claudeRow(doctor).kind
  if (claude === 'not-installed') return 'Claude is not installed'
  if (claude === 'signed-out' || claude === 'api-key') return 'Claude is not signed in'
  if (drive?.connected && drive.last_error) return 'Drive sync failed'
  return null
}
