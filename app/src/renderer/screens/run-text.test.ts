import { describe, expect, it } from 'vitest'
import type { InProgress } from '../api'
import { activityText, prepareText, runText } from './run-text'

const run = (steps: unknown[], over: Partial<InProgress> = {}): InProgress => ({ purpose: 'run', message: "'data' details", stage: 'scrape', site: 'jobindex', steps, ...over })

describe('runText: what a run is doing, in words, never its raw message', () => {
  it('says which step runs and how far it got', () => {
    const steps = [
      { name: 'search', status: 'running', detail: '', done: 1, total: 3, items: [] },
      { name: 'discover', status: 'running', detail: '' },
      { name: 'match', status: 'waiting', detail: '' },
    ]
    expect(runText(run(steps))).toBe('Finding new jobs: searching the job boards (1 of 3)')
  })

  it.each([
    ['follow', 12, 40, "Finding new jobs: looking up employers' career pages (12 of 40)"],
    ['collect', 3, 57, 'Finding new jobs: reading career pages (3 of 57)'],
    ['match', 12, 40, 'Finding new jobs: scoring the new ads (12 of 40)'],
  ])('says %s in words', (name, done, total, text) => {
    expect(runText(run([{ name, status: 'running', detail: '', done, total }]))).toBe(text)
  })

  it('leaves the count out when there is none, and says Discover only when nothing else runs', () => {
    expect(runText(run([{ name: 'match', status: 'running', detail: '', done: 0 }]))).toBe('Finding new jobs: scoring the new ads')
    expect(runText(run([{ name: 'discover', status: 'running', detail: '' }]))).toBe('Finding new jobs: finding employers')
  })

  it('says only that it is finding jobs between steps, or with no steps', () => {
    expect(runText(run([{ name: 'search', status: 'done', detail: 'x' }]))).toBe('Finding new jobs…')
    expect(runText(run([]))).toBe('Finding new jobs…')
    expect(runText({ purpose: 'search', message: 'jobindex: x' })).toBe('Finding new jobs…')
  })

  it('names a Prepare, and anything else plainly', () => {
    expect(runText({ purpose: 'prepare', message: 'verifying outputs for x' })).toBe('Preparing an application…')
    expect(runText({ purpose: 'sync', message: 'pulling' })).toBe('Working…')
  })
})

describe('activityText: what a board at work is doing', () => {
  it('reads ads, or searches a keyword', () => {
    expect(activityText({ kind: 'reading', keyword: 'data', done: 12, total: 40 })).toBe("reading ads for 'data' (12 of 40)")
    expect(activityText({ kind: 'searching', keyword: 'data', done: 3, total: 21 })).toBe("searching 'data' (keyword 3 of 21)")
  })
})

describe("prepareText: a Prepare's step in words", () => {
  it.each([
    ['selecting top match', 'Choosing the best match'],
    ['estimating the salary', 'Estimating the salary'],
    ['tailoring Acme: Data Analyst · 3m20s elapsed', 'Writing your CV and cover letter'],
    ['verifying outputs for Acme: Data Analyst', 'Checking the PDFs'],
    ['something new', 'Preparing…'],
  ])('%s', (message, text) => {
    expect(prepareText(message)).toBe(text)
  })
})
