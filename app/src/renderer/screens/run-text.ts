// What a run or a Prepare is doing, in words for the user. The progress messages are written for logs
// and the terminal (`'data' details`, `verifying outputs for …`), so a screen never shows them as they are:
// it says the step from the folded `steps`, and a Prepare's stage from the start of its message.
import type { InProgress, StepActivity, StepRow } from '../api'

const STEP_WORDS: Record<string, string> = {
  search: 'searching the job boards',
  discover: 'finding employers',
  follow: "looking up employers' career pages",
  collect: 'reading career pages',
  match: 'scoring the new ads',
}

// the lock purposes of `find` and its single steps
const FINDING = new Set(['run', 'scrape', 'search', 'discover', 'follow', 'collect', 'match'])

const isStep = (s: unknown): s is StepRow =>
  typeof s === 'object' && s !== null && typeof (s as StepRow).name === 'string' && typeof (s as StepRow).status === 'string'

/** One line for a run holding the lock, e.g. "Finding new jobs: scoring the new ads (12 of 40)". */
export function runText(progress: InProgress): string {
  const steps = Array.isArray(progress.steps) ? progress.steps.filter(isStep) : []
  if (progress.purpose === 'prepare') return 'Preparing an application…'
  if (!FINDING.has(progress.purpose ?? '') && steps.length === 0) return 'Working…'
  const running = steps.filter((s) => s.status === 'running')
  // Discover runs beside the others: say the step in front of it
  const step = running.find((s) => s.name !== 'discover') ?? running[0]
  const words = step && STEP_WORDS[step.name]
  if (!step || !words) return 'Finding new jobs…'
  const count = step.total ? ` (${step.done ?? 0} of ${step.total})` : ''
  return `Finding new jobs: ${words}${count}`
}

/** What a board at work is doing: "reading ads for 'data' (12 of 40)". */
export function activityText(a: StepActivity): string {
  return a.kind === 'reading' ? `reading ads for '${a.keyword}' (${a.done} of ${a.total})` : `searching '${a.keyword}' (keyword ${a.done} of ${a.total})`
}

const PREPARE_WORDS: [RegExp, string][] = [
  [/^selecting top match/, 'Choosing the best match'],
  [/^estimating the salary/, 'Estimating the salary'],
  [/^tailor/, 'Writing your CV and cover letter'],
  [/^verifying outputs|^CV, cover letter and both PDFs/, 'Checking the PDFs'],
]

/** A Prepare's progress message as the step it is on. */
export function prepareText(message: string): string {
  return PREPARE_WORDS.find(([re]) => re.test(message))?.[1] ?? 'Preparing…'
}
