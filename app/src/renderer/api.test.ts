// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { call, draftCv, findJobs, languageLine, statusSummary, statusWord, STATUSES, INTERVIEW_KINDS, materialUrl, visiblePages, type Materials, type Posting } from './api'
import tools from '../generated/tools.json'
import { mockDoor } from './testing'

afterEach(() => vi.restoreAllMocks())

describe('call', () => {
  it('a sync conflict comes back as an ApiError with conflict set', async () => {
    mockDoor({
      sync_data: () => {
        throw { message: 'both changed', conflict: true }
      },
    })
    await expect(call('sync_data')).rejects.toMatchObject({ name: 'ApiError', message: 'both changed', conflict: true })
  })

  it('without onProgress passes no call id and subscribes to nothing', async () => {
    const { call: raw, onProgress } = mockDoor({ status_summary: {} })
    await call('status_summary')
    expect(raw).toHaveBeenCalledWith('status_summary', {})
    expect(onProgress).not.toHaveBeenCalled()
  })

  it('with onProgress makes a call id, subscribes by it, and unsubscribes at the end', async () => {
    const unsubscribe = vi.fn()
    const { call: raw, onProgress } = mockDoor({ find_jobs: {} })
    onProgress.mockImplementation(() => unsubscribe)
    const cb = vi.fn()
    await call('find_jobs', { step: 'search' }, { onProgress: cb })
    const id = (raw.mock.calls[0] as unknown[])[2]
    expect(typeof id).toBe('string')
    expect(onProgress).toHaveBeenCalledWith(id, cb)
    expect(unsubscribe).toHaveBeenCalledTimes(1)
  })

  it('unsubscribes when the call fails', async () => {
    const unsubscribe = vi.fn()
    const { onProgress } = mockDoor({
      find_jobs: () => {
        throw { message: 'a run is in progress' }
      },
    })
    onProgress.mockImplementation(() => unsubscribe)
    await expect(call('find_jobs', {}, { onProgress: () => {} })).rejects.toThrow('a run is in progress')
    expect(unsubscribe).toHaveBeenCalledTimes(1)
  })
})

describe('statusSummary', () => {
  it('callers at the same time share one status_summary call; a later caller asks again', async () => {
    const { call: raw } = mockDoor({ status_summary: { min_score: 0.5 } })
    const [a, b] = await Promise.all([statusSummary(), statusSummary()])
    expect(a).toEqual({ min_score: 0.5 })
    expect(b).toBe(a)
    expect(raw).toHaveBeenCalledTimes(1)
    await statusSummary()
    expect(raw).toHaveBeenCalledTimes(2)
  })

  it('a failed call is not kept: the next caller asks again', async () => {
    let fail = true
    const { call: raw } = mockDoor({
      status_summary: () => {
        if (fail) throw { message: 'busy' }
        return { min_score: 0.5 }
      },
    })
    await expect(statusSummary()).rejects.toThrow('busy')
    fail = false
    await expect(statusSummary()).resolves.toEqual({ min_score: 0.5 })
    expect(raw).toHaveBeenCalledTimes(2)
  })
})

describe('status constants', () => {
  it('STATUSES and INTERVIEW_KINDS cover exactly the statuses set_status documents', () => {
    const desc = tools.find((t) => t.name === 'set_status')!.description
    const block = /status: One of: ([\s\S]*?discarded)/.exec(desc.replace(/\([^)]*\)/g, ''))![1]
    const documented = block.split(',').map((v) => v.trim()).filter(Boolean)
    const ours = STATUSES.flatMap((s) => (s.value === 'interview' ? INTERVIEW_KINDS.map((k) => k.value) : [s.value]))
    expect(ours.sort()).toEqual(documented.sort())
    expect(STATUSES).toHaveLength(8)
  })

  it('the four interview kinds come with a meaning', () => {
    expect(INTERVIEW_KINDS.map((k) => k.value)).toEqual([
      'interview:screening',
      'interview:impression',
      'interview:assessment',
      'interview:technical',
    ])
    for (const k of INTERVIEW_KINDS) expect(k.meaning.length).toBeGreaterThan(5)
  })


  it('a posting nobody acted on has no status word', () => {
    expect(statusWord('unapplied')).toBeNull()
  })
})

const materials = (over: Partial<Materials> = {}): Materials => ({
  output_dir: '/abs/jobs/output/jobindex.123',
  file_names: { cv: 'CV.pdf', cover_letter: 'Cover letter.pdf' },
  pdfs: { cv: '/abs/jobs/output/jobindex.123/cv.pdf', cover_letter: '/abs/jobs/output/jobindex.123/cover_letter.pdf' },
  pngs: {
    cv: ['/abs/jobs/output/jobindex.123/cv_page_1.png', '/abs/jobs/output/jobindex.123/cv_page_2.png', '/abs/jobs/output/jobindex.123/cv_page_3.png'],
    cover_letter: ['/abs/jobs/output/jobindex.123/cover_letter_page_1.png'],
  },
  keywords: ['sql'],
  tailoring: [],
  page_counts: { cv: 2, cover_letter: 1 },
  cover_letter_words: 310,
  rendered: false,
  ...over,
})

describe('materials helpers', () => {
  it('materialUrl points into sent/ for the copy that was sent', () => {
    expect(materialUrl('jobindex.123', '/abs/jobs/output/jobindex.123/sent/cv_page_1.png', 0, true)).toBe('door-file://output/jobindex.123/sent/cv_page_1.png?v=0')
  })

  it('materialUrl names the job and page, never a path, with a cache counter', () => {
    expect(materialUrl('jobindex.123', '/abs/jobs/output/jobindex.123/cv_page_1.png', 2)).toBe(
      'door-file://output/jobindex.123/cv_page_1.png?v=2',
    )
  })

  it('visiblePages drops stale images beyond the page count', () => {
    expect(visiblePages(materials(), 'cv')).toHaveLength(2)
    expect(visiblePages(materials(), 'cover_letter')).toHaveLength(1)
  })

  it('a Posting has materials or null', () => {
    const p: Pick<Posting, 'materials'> = { materials: null }
    const q: Pick<Posting, 'materials'> = { materials: materials() }
    expect([p, q]).toHaveLength(2)
  })
})


describe('findJobs', () => {
  const record = { started_at: 's', new_above_threshold: [], top: [], failures: [] }

  it('runs the whole pipeline by default, with progress so the idle limit restarts', async () => {
    const { call: raw, onProgress } = mockDoor({ find_jobs: record })
    const out = await findJobs()
    expect(out).toEqual({ kind: 'done', record })
    expect(raw.mock.calls[0][0]).toBe('find_jobs')
    expect(raw.mock.calls[0][1]).toEqual({})
    expect(onProgress).toHaveBeenCalledTimes(1)
  })

  it('passes a skip list of steps as it is', async () => {
    const { call: raw } = mockDoor({ find_jobs: record })
    await findJobs({ skip: ['discover', 'follow', 'collect'] })
    expect(raw.mock.calls[0][1]).toEqual({ skip: ['discover', 'follow', 'collect'] })
  })

  it('hands the progress lines to the caller', async () => {
    const { emitProgress } = mockDoor({
      find_jobs: async () => {
        emitProgress({ progress: 1, message: 'search: started' })
        return record
      },
    })
    const lines: string[] = []
    await findJobs({ onLine: (l) => lines.push(l) })
    expect(lines).toEqual(['search: started'])
  })

  it('maps a run in progress elsewhere to busy', async () => {
    mockDoor({
      find_jobs: () => {
        throw { message: 'a run is in progress (started 06:30, pid 4242); try again when it has finished' }
      },
    })
    expect(await findJobs()).toEqual({ kind: 'busy' })
  })

  it('maps the in-app busy text (prepare is running) to preparing, not to a run in progress', async () => {
    mockDoor({
      find_jobs: () => {
        throw { message: 'another long-running tool (find_jobs or prepare) is already in progress; wait for it to finish before calling again' }
      },
    })
    expect(await findJobs()).toEqual({ kind: 'preparing' })
  })

  it('maps a stopped run to stopped, and any other failure to its words', async () => {
    const { call: raw } = mockDoor({})
    raw.mockResolvedValueOnce({ ok: false, error: 'stopped', stopped: true } as never)
    expect(await findJobs()).toEqual({ kind: 'stopped' })
    raw.mockResolvedValueOnce({ ok: false, error: 'profile/config.json is missing' } as never)
    expect(await findJobs()).toEqual({ kind: 'error', message: 'profile/config.json is missing' })
  })
})


describe('draftCv', () => {
  it('sends tokens and urls through the draft channel, never the generic call', async () => {
    const h = mockDoor({ draft_cv: { markdown: '# Ada', sources: [], provenance: [], todos: [] } })
    const r = await draftCv({ files: ['tok'], urls: ['https://a.com'] })
    expect(r.markdown).toBe('# Ada')
    expect(h.draftCv).toHaveBeenCalledWith({ files: ['tok'], urls: ['https://a.com'] })
    expect(h.call).not.toHaveBeenCalled()
  })

  it('throws an ApiError with the words of a failed draft', async () => {
    mockDoor({ draft_cv: () => { throw { message: 'claude is not signed in' } } })
    await expect(draftCv({ files: [], urls: ['https://a.com'] })).rejects.toThrow('claude is not signed in')
  })
})

describe('languageLine', () => {
  it('names the ad language in English with what it asks of you', () => {
    expect(languageLine('da', 'required')).toBe('Danish — required')
    expect(languageLine('fr', 'advantage')).toBe('French — an advantage')
    expect(languageLine('hu')).toBe('Hungarian')
  })
})
