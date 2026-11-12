import { describe, expect, it } from 'vitest'
import { inPlayStatus, needsJob, noticeFor, type NoticeEvent } from './notices'

const job = { title: 'Data Analyst', company: 'Acme', inPlay: false }
const record = (over: Record<string, unknown> = {}) => ({
  started_at: '2026-10-29T08:00:00',
  finished_at: '2026-10-29T08:30:00',
  search: { sites: [{ site: 'jobindex', outcome: 'ok' }] },
  collect: null,
  new_above_threshold: ['jobindex.1', 'jobindex.2', 'jobindex.3'],
  ...over,
})
const done = (tool: string, result: unknown, args: Record<string, unknown> = {}): NoticeEvent => ({ kind: 'call', tool, args, result })
const failed = (tool: string, message: string, extra: Record<string, unknown> = {}, args: Record<string, unknown> = {}): NoticeEvent => ({
  kind: 'call-error',
  tool,
  args,
  error: { message, ...extra },
})

describe('search finished', () => {
  it('counts the new matches and opens Matches with New only', () => {
    expect(noticeFor(done('find_jobs', record()))).toEqual({
      title: 'New jobs found',
      body: '3 new matches',
      target: { screen: 'matches', newOnly: true },
    })
  })
  it('says one match in the singular', () => {
    expect(noticeFor(done('find_jobs', record({ new_above_threshold: ['a.1'] })))?.body).toBe('1 new match')
  })
  it('says so when nothing new cleared the bar, and opens the Finding summary', () => {
    expect(noticeFor(done('find_jobs', record({ new_above_threshold: [] })))).toEqual({
      title: 'No new matches',
      body: 'Nothing new this time',
      target: { screen: 'finding' },
    })
  })
  it('survives an odd record', () => {
    expect(noticeFor(done('find_jobs', {}))?.title).toBe('No new matches')
    expect(noticeFor(done('find_jobs', null))?.title).toBe('No new matches')
  })
})

describe('search failed', () => {
  it('an idle timeout', () => {
    expect(noticeFor(failed('find_jobs', 'x', { timedOut: true }))).toEqual({
      title: 'The search stopped',
      body: 'The other door heard nothing for 15 minutes. Nothing is lost; run it again.',
      target: { screen: 'finding' },
    })
  })
  it('another error gives its first line', () => {
    expect(noticeFor(failed('find_jobs', 'The claude CLI is not signed in\nTraceback ...'))).toEqual({
      title: "The search didn't finish",
      body: 'The claude CLI is not signed in',
      target: { screen: 'finding' },
    })
  })
})

describe('prepare', () => {
  it.each(['prepared', 'skipped'])('%s is an application ready to send', (outcome) => {
    const event = done('prepare', { outcome, job_id: 'jobindex.1' })
    expect(needsJob(event)).toBe(true)
    expect(noticeFor({ ...event, job } as NoticeEvent)).toEqual({
      title: 'Application ready',
      body: 'Data Analyst · Acme: the CV and letter are ready to send.',
      target: { screen: 'materials', jobId: 'jobindex.1', inPlay: true },
    })
  })
  it('without the job words the body stays plain', () => {
    expect(noticeFor(done('prepare', { outcome: 'prepared', job_id: 'jobindex.1' }))?.body).toBe('The CV and letter are ready to send.')
  })
  it('no_matches and failed outcomes are not announced', () => {
    expect(noticeFor(done('prepare', { outcome: 'no_matches', job_id: null }))).toBeNull()
    expect(noticeFor(done('prepare', { outcome: 'failed', job_id: 'jobindex.1' }))).toBeNull()
    expect(needsJob(done('prepare', { outcome: 'failed', job_id: 'jobindex.1' }))).toBe(false)
  })
  it('an error opens the posting', () => {
    const event = failed('prepare', 'LaTeX is missing\nmore', {}, { job_id: 'jobindex.1' })
    expect(needsJob(event)).toBe(true)
    expect(noticeFor({ ...event, job: { ...job, inPlay: true } } as NoticeEvent)).toEqual({
      title: "Preparing didn't finish",
      body: 'Data Analyst · Acme: LaTeX is missing',
      target: { screen: 'posting', jobId: 'jobindex.1', inPlay: true },
    })
  })
  it('an error without a job id still tells', () => {
    const n = noticeFor(failed('prepare', 'no luck'))
    expect(n).toEqual({ title: "Preparing didn't finish", body: 'no luck', target: { screen: 'matches' } })
  })
  it('refusals and a Stop are silent', () => {
    expect(noticeFor(failed('prepare', 'A run is in progress (started 09:12)'))).toBeNull()
    expect(noticeFor(failed('prepare', 'another long-running tool is running'))).toBeNull()
    expect(noticeFor(failed('prepare', 'stopped', { stopped: true }))).toBeNull()
    expect(noticeFor(failed('find_jobs', 'A run is in progress', {}))).toBeNull()
    expect(noticeFor(failed('find_jobs', 'another long-running tool', {}))).toBeNull()
    expect(noticeFor(failed('find_jobs', 'x', { stopped: true }))).toBeNull()
  })
})

describe('revise', () => {
  const revised = (file: string, compile?: unknown) => ({ ...done('revise', { outcome: 'revised', job_id: 'jobindex.1', file, ...(compile ? { compile } : {}) }), job }) as NoticeEvent
  it('a CV revision', () => {
    expect(noticeFor(revised('cv.tex'))).toEqual({
      title: 'Revision done',
      body: 'Data Analyst · Acme: the CV is updated.',
      target: { screen: 'materials', jobId: 'jobindex.1', inPlay: false, document: 'cv' },
    })
  })
  it('a letter revision', () => {
    const n = noticeFor(revised('cover_letter.tex', [{ file: 'cover_letter.tex', status: 'compiled' }]))
    expect(n?.body).toBe('Data Analyst · Acme: the letter is updated.')
    expect(n?.target).toEqual({ screen: 'materials', jobId: 'jobindex.1', inPlay: false, document: 'cover_letter' })
  })
  it('a compile error', () => {
    expect(noticeFor(revised('cv.tex', [{ file: 'cv.tex', status: 'error' }]))).toEqual({
      title: 'The PDF could not be rebuilt',
      body: 'Undo last change puts it back.',
      target: { screen: 'materials', jobId: 'jobindex.1', inPlay: false, document: 'cv' },
    })
  })
  it('an undo is silent', () => {
    expect(noticeFor(done('revise', { outcome: 'undone', job_id: 'jobindex.1', file: 'cv.tex' }))).toBeNull()
  })
})

describe('import_posting', () => {
  it('scored', () => {
    const event = { ...done('import_posting', { job_id: 'jobindex.9', score: 0.81 }, { url: 'https://example.com/ad' }), job } as NoticeEvent
    expect(noticeFor(event)).toEqual({
      title: 'Ad imported',
      body: 'Data Analyst · Acme: scored 0.81',
      target: { screen: 'posting', jobId: 'jobindex.9', inPlay: false },
    })
  })
  it('not scored', () => {
    expect(noticeFor({ ...done('import_posting', { job_id: 'jobindex.9', score: null }, { url: 'https://example.com/ad' }), job } as NoticeEvent)?.body).toBe('Data Analyst · Acme: not scored yet')
  })
  it('a pasted ad is quick and stays silent; only an import by link is announced', () => {
    expect(noticeFor({ ...done('import_posting', { job_id: 'manual.1', score: 0.7 }, { text: 'ad', title: 'T', company: 'C' }), job } as NoticeEvent)).toBeNull()
  })
})

describe('a run started elsewhere', () => {
  const ended = (started_at: string | null): NoticeEvent => ({
    kind: 'foreign-run-ended',
    startedAt: '2026-10-29T08:00:00',
    lastRun: started_at ? { started_at, new_above_threshold: 2 } : null,
  })
  it('counts the new matches when the record is from that run', () => {
    expect(noticeFor(ended('2026-10-29T08:00:05'))).toEqual({ title: 'A run finished', body: '2 new matches', target: { screen: 'matches', newOnly: true } })
  })
  it('never reports a stale record', () => {
    const n = noticeFor(ended('2026-10-28T08:00:00'))
    expect(n?.title).toBe('A run finished')
    expect(n?.body).not.toMatch(/\d/)
    expect(noticeFor(ended(null))?.body).not.toMatch(/\d/)
  })
})

describe('quiet tools and words', () => {
  it.each(['show', 'list_matches', 'set_status', 'mark_reviewed', 'status_summary'])('%s is never announced', (tool) => {
    expect(noticeFor(done(tool, { job_id: 'jobindex.1' }))).toBeNull()
    expect(needsJob(done(tool, { job_id: 'jobindex.1' }))).toBe(false)
  })
  it('no notice carries a raw id or a path', () => {
    const events: NoticeEvent[] = [
      done('find_jobs', record()),
      { ...done('prepare', { outcome: 'prepared', job_id: 'jobindex.1' }), job } as NoticeEvent,
      { ...done('import_posting', { job_id: 'jobindex.9', score: 0.5 }, { url: 'https://example.com/ad' }), job } as NoticeEvent,
      { ...done('revise', { outcome: 'revised', job_id: 'jobindex.1', file: 'cv.tex' }), job } as NoticeEvent,
    ]
    for (const e of events) {
      const n = noticeFor(e)!
      expect(`${n.title} ${n.body}`).not.toMatch(/jobindex\.\d|\.tex|\/|unapplied/)
    }
  })
})

describe('inPlayStatus', () => {
  it('is true for the statuses that live on Applications', () => {
    for (const s of ['prepared', 'applied', 'interview:technical', 'offer']) expect(inPlayStatus(s)).toBe(true)
    for (const s of ['unapplied', 'discarded', 'rejected', 'ghosted', '']) expect(inPlayStatus(s)).toBe(false)
  })
})
