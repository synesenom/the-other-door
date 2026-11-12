// What the desktop app says when a long job finishes: a pure map from a settled call (or a run
// started elsewhere that ended) to a notification in words, or null when nothing should be said.
// The words of a job (title, company) are fetched by the caller and handed in as `job`.
// No electron or fs imports: notifier.ts shows it, ipc.ts and index.ts feed it.

export type NoticeTarget =
  | { screen: 'matches'; newOnly?: boolean }
  | { screen: 'finding' }
  | { screen: 'materials'; jobId: string; inPlay: boolean; document?: 'cv' | 'cover_letter' }
  | { screen: 'posting'; jobId: string; inPlay: boolean }

export interface Notice {
  title: string
  body: string
  target: NoticeTarget
}

/** A job in words, from `show`; `inPlay` is whether it lives on Applications. */
export interface JobWords {
  title: string
  company: string
  inPlay: boolean
}

export type NoticeEvent = (
  | { kind: 'call'; tool: string; args: Record<string, unknown>; result: unknown }
  | { kind: 'call-error'; tool: string; args: Record<string, unknown>; error: { message: string; timedOut?: boolean; stopped?: boolean } }
  | {
      kind: 'foreign-run-ended'
      startedAt: string
      lastRun: { started_at?: string; new_above_threshold?: number } | null
    }
) & { job?: JobWords }

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const JOB_TOOLS = new Set(['prepare', 'revise', 'import_posting'])
const MAX_LINE = 200

/** A status that puts a job on the Applications screen rather than Matches. */
export function inPlayStatus(status: string): boolean {
  return status === 'prepared' || status === 'applied' || status === 'offer' || status.startsWith('interview:')
}

const firstLine = (message: string) => (message.split('\n').find((l) => l.trim()) ?? '').trim().slice(0, MAX_LINE)
const refusal = (message: string) => /is in progress|another long-running tool/.test(message)
const plural = (n: number) => `${n} new ${n === 1 ? 'match' : 'matches'}`

function jobId(event: NoticeEvent): string | null {
  if (event.kind === 'foreign-run-ended') return null
  const fromResult = event.kind === 'call' && isObject(event.result) && typeof event.result['job_id'] === 'string' ? event.result['job_id'] : null
  const fromArgs = typeof event.args['job_id'] === 'string' ? (event.args['job_id'] as string) : null
  return fromResult ?? fromArgs
}

const withJob = (job: JobWords | undefined, text: string, plain: string) => (job ? `${job.title} · ${job.company}: ${text}` : plain)

function searchDone(result: unknown): Notice {
  const record = isObject(result) ? result : {}
  const found = Array.isArray(record['new_above_threshold']) ? record['new_above_threshold'].length : 0
  return found > 0
    ? { title: 'New jobs found', body: plural(found), target: { screen: 'matches', newOnly: true } }
    : { title: 'No new matches', body: 'Nothing new this time', target: { screen: 'finding' } }
}

function noticeForCall(event: Extract<NoticeEvent, { kind: 'call' }>): Notice | null {
  const result = isObject(event.result) ? event.result : {}
  const id = jobId(event)
  switch (event.tool) {
    case 'find_jobs':
      return searchDone(event.result)
    case 'prepare':
      if ((result['outcome'] !== 'prepared' && result['outcome'] !== 'skipped') || !id) return null
      return {
        title: 'Application ready',
        body: withJob(event.job, 'the CV and letter are ready to send.', 'The CV and letter are ready to send.'),
        target: { screen: 'materials', jobId: id, inPlay: true }, // a prepared job is in play
      }
    case 'revise': {
      if (result['outcome'] !== 'revised' || !id) return null
      const file = String(result['file'] ?? '')
      const document = file.startsWith('cover_letter') ? 'cover_letter' : 'cv'
      const compile = Array.isArray(result['compile']) ? result['compile'] : []
      const target: NoticeTarget = { screen: 'materials', jobId: id, inPlay: event.job?.inPlay ?? false, document }
      if (compile.some((c) => isObject(c) && c['status'] === 'error')) {
        return { title: 'The PDF could not be rebuilt', body: 'Undo last change puts it back.', target }
      }
      const what = document === 'cv' ? 'CV' : 'letter'
      return { title: 'Revision done', body: withJob(event.job, `the ${what} is updated.`, `The ${what} is updated.`), target }
    }
    case 'import_posting': {
      // A pasted ad is stored and scored in seconds; only an import by link (a page fetch and a read) is long.
      if (!id || typeof event.args?.['url'] !== 'string') return null
      const scored = typeof result['score'] === 'number' ? `scored ${(result['score'] as number).toFixed(2)}` : 'not scored yet'
      return {
        title: 'Ad imported',
        body: withJob(event.job, scored, `${scored[0].toUpperCase()}${scored.slice(1)}`),
        target: { screen: 'posting', jobId: id, inPlay: event.job?.inPlay ?? false },
      }
    }
    default:
      return null
  }
}

function noticeForError(event: Extract<NoticeEvent, { kind: 'call-error' }>): Notice | null {
  const { error } = event
  if (error.stopped || refusal(error.message)) return null
  if (event.tool === 'find_jobs') {
    return error.timedOut
      ? { title: 'The search stopped', body: 'The other door heard nothing for 15 minutes. Nothing is lost; run it again.', target: { screen: 'finding' } }
      : { title: "The search didn't finish", body: firstLine(error.message), target: { screen: 'finding' } }
  }
  if (event.tool === 'prepare') {
    const id = jobId(event)
    const line = firstLine(error.message)
    return {
      title: "Preparing didn't finish",
      body: withJob(event.job, line, line),
      target: id ? { screen: 'posting', jobId: id, inPlay: event.job?.inPlay ?? false } : { screen: 'matches' },
    }
  }
  return null
}

export function noticeFor(event: NoticeEvent): Notice | null {
  if (event.kind === 'call') return noticeForCall(event)
  if (event.kind === 'call-error') return noticeForError(event)
  const run = event.lastRun
  const fresh = run && typeof run.started_at === 'string' && run.started_at >= event.startedAt && typeof run.new_above_threshold === 'number'
  return {
    title: 'A run finished',
    body: fresh ? plural(run.new_above_threshold as number) : 'Open The other door to see what it found.',
    target: { screen: 'matches', newOnly: true },
  }
}

/** Whether the notice for this event wants the job's words (one `show` call by the caller). */
export function needsJob(event: NoticeEvent): boolean {
  if (event.kind === 'foreign-run-ended' || !JOB_TOOLS.has(event.tool)) return false
  return jobId(event) !== null && noticeFor({ ...event, job: undefined }) !== null
}
