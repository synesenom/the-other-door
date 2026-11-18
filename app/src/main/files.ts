// Where a job's prepared files live, and the only way the app names one: a job id
// plus a fixed file name, never a path from the renderer. Pure (no processes).
import { existsSync, realpathSync } from 'node:fs'
import { homedir } from 'node:os'
import { join, resolve, sep } from 'node:path'

/** The data folder, by the rule of src/door/core/workspace.py: DOOR_HOME (a leading ~ expanded), else the checkout. */
export function doorHome(env: Record<string, string | undefined>, repoRoot: string): string {
  const raw = env['DOOR_HOME']
  if (!raw) return resolve(repoRoot)
  if (raw === '~') return homedir()
  if (raw.startsWith('~/')) return resolve(join(homedir(), raw.slice(2)))
  return resolve(raw)
}

export function isJobId(v: unknown): v is string {
  return typeof v === 'string' && /^[\w.-]+$/.test(v) && v !== '.' && v !== '..'
}

export type Material = 'cv' | 'cover_letter'

export function isMaterialName(v: unknown): v is Material {
  return v === 'cv' || v === 'cover_letter'
}

export function isPngName(v: unknown): v is string {
  return typeof v === 'string' && /^(cv|cover_letter)_page_\d+\.png$/.test(v)
}

/**
 * `home/jobs/output/<jobId>/<file>` (`<jobId>/sent/<file>` with *sent*: the copy kept when the application was sent)
 * when the name is one of ours, the file exists and, symlinks resolved, stays under jobs/output.
 */
export function materialPath(home: string, jobId: unknown, file: unknown, sent = false): string | null {
  if (!isJobId(jobId) || typeof file !== 'string') return null
  const pdf = /^(cv|cover_letter)\.pdf$/.test(file)
  if (!pdf && !isPngName(file)) return null
  const candidate = sent ? join(home, 'jobs', 'output', jobId, 'sent', file) : join(home, 'jobs', 'output', jobId, file)
  return contained(candidate, join(home, 'jobs', 'output'))
}

/** `candidate` when it exists and, links resolved, still lies under `root`; else null. */
export function contained(candidate: string, root: string): string | null {
  try {
    if (!existsSync(candidate)) return null
    return realpathSync(candidate).startsWith(realpathSync(root) + sep) ? candidate : null
  } catch {
    return null
  }
}

/** `home/jobs/runs/<started_at>.json` when it exists; the name follows `_run_record_filename` in src/door/commands/find.py. */
export function runRecordPath(home: string, startedAt: unknown): string | null {
  if (typeof startedAt !== 'string' || startedAt.length === 0 || startedAt.length > 64) return null
  const path = join(home, 'jobs', 'runs', `${startedAt.replace(/[^A-Za-z0-9_-]/g, '-')}.json`)
  return existsSync(path) ? path : null
}

export interface PickedRule {
  /** Accepted endings without the dot, e.g. `pdf`, `tar.gz`; matched without regard to case. */
  extensions: string[]
  /** The size cap, when there is one. */
  maxBytes?: number
  wrongType: string
  tooBig?: string
  unreadable?: string
}

/**
 * The rule for a file picked in a dialog: the name picked and the file behind it (links resolved) both end in
 * an accepted extension, and the file is under the size cap; else a reason in words. Returns the real path.
 */
export async function checkPicked(
  path: string,
  rule: PickedRule,
  io: { realpath?: (p: string) => Promise<string>; stat: (p: string) => Promise<{ size: number }> },
): Promise<{ ok: true; real: string; size: number } | { ok: false; error: string }> {
  const accepted = (p: string) => rule.extensions.some((e) => p.toLowerCase().endsWith(`.${e}`))
  if (!accepted(path)) return { ok: false, error: rule.wrongType }
  let real: string
  let size = 0
  try {
    real = io.realpath ? await io.realpath(path) : path
    if (!accepted(real)) return { ok: false, error: rule.wrongType }
    if (rule.maxBytes !== undefined) size = (await io.stat(real)).size
  } catch {
    return { ok: false, error: rule.unreadable ?? 'That file could not be read.' }
  }
  if (rule.maxBytes !== undefined && size > rule.maxBytes) return { ok: false, error: rule.tooBig ?? 'That file is too big.' }
  return { ok: true, real, size }
}
