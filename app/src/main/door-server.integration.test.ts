// The real Python server over stdio on a generated home. Slow; not part of
// `npm test` (CI's app job has no Python). Run with `npm run test:integration`.
import { existsSync, readFileSync, realpathSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { buildEmptyHome, buildHome, repoRoot } from '../../test/home-fixture'
import { doorHome } from './files'
import { DoorServer, resolveSpawn } from './door-server'

const fixture = buildHome()
const { hasPython } = fixture
if (!hasPython) console.warn(`skipping the real-server test: no ${fixture.python} (set DOOR_PYTHON)`)

describe.skipIf(!hasPython)('DoorServer against the real door server', () => {
  let home: string
  let server: DoorServer

  beforeAll(() => {
    home = fixture.home
    server = new DoorServer(resolveSpawn(repoRoot, fixture.env))
  })

  afterAll(async () => {
    await server?.close()
  })

  it('lists matches best first', async () => {
    const r = await server.call<{ matches: { id: string; title: string; title_en?: string }[] }>('list_matches')
    expect(r.matches.map((m) => m.id)).toEqual(['jobindex.123', 'jobindex.456'])
    expect(r.matches[0].title_en).toBe('Data Analyst')
  })

  it('shows one posting with its score reason', async () => {
    const p = await server.call<{ title: string; score_reason: string }>('show', { job_id: 'jobindex.123' })
    expect(p.title).toBe('Dataanalytiker')
    expect(p.score_reason).toBe('Strong match on SQL.')
  })

  it('discarding hides the job and writes the reason to the ledger', async () => {
    await server.call('set_status', { job_id: 'jobindex.456', status: 'discarded', notes: 'too far' })
    const r = await server.call<{ matches: { id: string }[] }>('list_matches')
    expect(r.matches.map((m) => m.id)).toEqual(['jobindex.123'])
    const ledger = JSON.parse(readFileSync(join(home, 'jobs', 'applications.json'), 'utf8'))
    const entry = ledger['jobindex.456']
    expect(entry.status).toBe('discarded')
    expect(entry.history.some((h: { notes?: string }) => h.notes === 'too far')).toBe(true)
  })

  it('status_summary has the keys the header reads', async () => {
    const s = await server.call<Record<string, unknown>>('status_summary')
    for (const key of ['min_score', 'pipeline', 'since_last_review', 'in_progress']) expect(s).toHaveProperty(key)
  })

  it('recovers from a killed child on the next call', async () => {
    await server.call('list_matches')
    const pid = server.pid
    expect(pid).not.toBeNull()
    process.kill(pid!)
    const end = Date.now() + 5000
    while (server.pid !== null && Date.now() < end) await new Promise((r) => setTimeout(r, 20))
    const r = await server.call<{ matches: unknown[] }>('list_matches')
    expect(r.matches).toHaveLength(1)
    expect(server.pid).not.toBe(pid)
  })
})

// Each group gets its own home, so the ledger of one never reaches another.
describe.skipIf(!hasPython)('daily-use tools against the real door server', () => {
  const ledgerOf = (home: string) => JSON.parse(readFileSync(join(home, 'jobs', 'applications.json'), 'utf8'))

  async function withServer<T>(
    run: (server: DoorServer, home: string, env: Record<string, string>) => Promise<T>,
    options: { prepared?: string } = {},
  ): Promise<T> {
    const own = buildHome(options)
    const server = new DoorServer(resolveSpawn(repoRoot, own.env))
    try {
      return await run(server, own.home, own.env)
    } finally {
      await server.close()
    }
  }

  it('a prepare that runs the tailor meets the stand-in claude, never the real one', async () => {
    await withServer(async (server, home) => {
      await server.call('prepare', { job_id: 'jobindex.456' }).catch(() => undefined)
      // The home fixture's claude leaves this mark when it is run.
      expect(existsSync(join(home, '..', 'claude-was-called'))).toBe(true)
    })
  })

  it('records each interview kind, with notes', async () => {
    await withServer(async (server, home) => {
      for (const kind of ['screening', 'impression', 'assessment', 'technical']) {
        const r = await server.call<{ current: string }>('set_status', {
          job_id: 'jobindex.123',
          status: `interview:${kind}`,
          notes: `went well: ${kind}`,
        })
        expect(r.current).toBe(`interview:${kind}`)
      }
      const entry = ledgerOf(home)['jobindex.123']
      expect(entry.status).toBe('interview:technical')
      expect(entry.history.map((h: { status: string }) => h.status)).toEqual([
        'interview:screening',
        'interview:impression',
        'interview:assessment',
        'interview:technical',
      ])
      expect(entry.history[0].notes).toBe('went well: screening')
    })
  })

  it('records an application, and it is ongoing', async () => {
    await withServer(async (server, home) => {
      await server.call('set_status', { job_id: 'jobindex.456', status: 'applied' })
      const entry = ledgerOf(home)['jobindex.456']
      expect(entry.status).toBe('applied')
      const ongoing = await server.call<{ matches: { id: string; status: string }[] }>('list_matches', { ongoing: true })
      expect(ongoing.matches.map((m) => [m.id, m.status])).toEqual([['jobindex.456', 'applied']])
    })
  })

  it('mark_reviewed clears what is new', async () => {
    await withServer(async (server) => {
      const before = await server.call<{ matches: unknown[] }>('list_matches', { new_only: true })
      expect(before.matches.length).toBeGreaterThan(0)
      const r = await server.call<{ reviewed_at: string }>('mark_reviewed')
      expect(typeof r.reviewed_at).toBe('string')
      const after = await server.call<{ matches: unknown[] }>('list_matches', { new_only: true })
      expect(after.matches).toEqual([])
      const s = await server.call<{ since_last_review: { new_matches: number } }>('status_summary')
      expect(s.since_last_review.new_matches).toBe(0)
    })
  })

  it('imports pasted text as a manual posting, not scored without a profile', async () => {
    await withServer(async (server) => {
      const r = await server.call<{ job_id: string; score: number | null; score_error?: string }>('import_posting', {
        text: 'We are hiring an analyst to work with SQL.',
        title: 'Analyst',
        company: 'Newco',
      })
      expect(r.job_id).toMatch(/^manual\./)
      expect(r.score).toBeNull()
      expect(r.score_error).toBeTruthy()
    })
  })

  describe('a prepared job', () => {
    it('shows its materials: page counts, keywords, tailoring, nothing rendered', async () => {
      await withServer(async (server) => {
        const p = await server.call<{ status: string; materials: Record<string, any> | null }>('show', { job_id: 'jobindex.123' })
        expect(p.status).toBe('prepared')
        const m = p.materials!
        expect(m.page_counts).toEqual({ cv: 2, cover_letter: 1 })
        expect(m.keywords).toEqual(['SQL', 'dashboards', 'stakeholder reporting'])
        expect(m.tailoring).toEqual(['Led with the dashboards project', 'Cut the retail job', 'Condensed education'])
        expect(m.cover_letter_words).toBeGreaterThanOrEqual(250)
        expect(m.cover_letter_words).toBeLessThanOrEqual(350)
        expect(m.rendered).toBe(false)
        expect(m.pngs.cv).toHaveLength(2)
        expect(m.pngs.cover_letter).toHaveLength(1)
      }, { prepared: 'jobindex.123' })
    })

    it('has no materials for a job nobody prepared', async () => {
      await withServer(async (server) => {
        const p = await server.call<{ materials: unknown }>('show', { job_id: 'jobindex.456' })
        expect(p.materials).toBeNull()
      }, { prepared: 'jobindex.123' })
    })

    it('prepare answers skipped for it, without a model', async () => {
      await withServer(async (server) => {
        const r = await server.call<{ outcome: string; files: string[] }>('prepare', { job_id: 'jobindex.123' })
        expect(r.outcome).toBe('skipped')
        expect(r.files).toContain('cv.pdf')
      }, { prepared: 'jobindex.123' })
    })

    it("keeps the output folder where the app's own HOME rule says (no drift from the server)", async () => {
      await withServer(async (server, _home, env) => {
        const p = await server.call<{ materials: { output_dir: string } }>('show', { job_id: 'jobindex.123' })
        const root = realpathSync(join(doorHome(env, repoRoot), 'jobs', 'output'))
        expect(realpathSync(p.materials.output_dir).startsWith(root + '/')).toBe(true)
        expect(realpathSync(p.materials.output_dir)).toBe(join(root, 'jobindex.123'))
      }, { prepared: 'jobindex.123' })
    })
  })
})

// The first launch: a home with nothing in it, and the stand-in claude that always fails.
describe.skipIf(!hasPython)('the onboarding tools against the real door server, on an empty home', () => {
  async function withEmptyServer<T>(run: (server: DoorServer, home: string) => Promise<T>): Promise<T> {
    const own = buildEmptyHome()
    const server = new DoorServer(resolveSpawn(repoRoot, own.env))
    try {
      return await run(server, own.home)
    } finally {
      await server.close()
    }
  }
  interface Shown {
    config: unknown
    errors: string[]
    cv: { exists: boolean; is_example: boolean; text: string | null }
    options: { cities: { name: string; country: string; boards: string[] }[]; languages: string[]; worldwide_boards: string[] }
  }
  const fields = { name: 'Ada Lovelace', email: 'ada@example.com', location: 'Copenhagen', languages: ['English'], role_targets: ['Data Scientist'], search_keywords: ['data scientist'], remote: 'hybrid', min_score: 0.65, exclude_companies: [], exclude_keywords: [] }

  it('show_profile has no config and lists the cities, languages and boards', async () => {
    await withEmptyServer(async (server) => {
      const p = await server.call<Shown>('show_profile')
      expect(p.config).toBeNull()
      expect(p.cv.exists).toBe(false)
      expect(p.options.cities.length).toBeGreaterThan(0)
      expect(p.options.cities[0]).toHaveProperty('boards')
      expect(p.options.languages).toContain('English')
      expect(p.options.worldwide_boards.length).toBeGreaterThan(0)
    })
  })

  it('init_profile with no role target refuses with a line per field', async () => {
    await withEmptyServer(async (server) => {
      await expect(server.call('init_profile', { ...fields, role_targets: [] })).rejects.toThrow(/profile\/config\.json: role_targets — /)
      expect((await server.call<Shown>('show_profile')).config).toBeNull()
    })
  })

  it('a valid init_profile, then save_cv, leaves a profile with the CV that was written', async () => {
    await withEmptyServer(async (server, home) => {
      await server.call('init_profile', fields)
      // init_profile writes no CV: until save_cv there is none
      expect((await server.call<Shown>('show_profile')).cv.exists).toBe(false)
      await server.call('save_cv', { markdown: '# Ada Lovelace\n\nData scientist.\n' })
      const after = await server.call<Shown>('show_profile')
      expect(after.config).not.toBeNull()
      expect(after.cv.is_example).toBe(false)
      expect(readFileSync(join(home, 'profile', 'cv.md'), 'utf8')).toBe('# Ada Lovelace\n\nData scientist.\n')
    })
  })

  it('save_cv refuses empty text', async () => {
    await withEmptyServer(async (server, home) => {
      await expect(server.call('save_cv', { markdown: '  ' })).rejects.toThrow(/empty/)
      expect(existsSync(join(home, 'profile', 'cv.md'))).toBe(false)
    })
  })

  it('keywords fails without a signed-in claude, the case the wizard falls back from', async () => {
    await withEmptyServer(async (server) => {
      await expect(server.call('keywords', { role_targets: ['Data Scientist'], languages: ['English'] })).rejects.toThrow()
    })
  })

  describe('draft_cv with files', () => {
    it('reads a Markdown file on the server, then meets the stand-in claude (which fails)', async () => {
      await withEmptyServer(async (server, home) => {
        const file = join(home, '..', 'my-cv.md')
        writeFileSync(file, '# Ada Lovelace\n\nData scientist with ten years of analysis.\n')
        await expect(server.call('draft_cv', { sources: [file] })).rejects.toThrow()
        await expect(server.call('draft_cv', { sources: [file] })).rejects.not.toThrow(/no such file|must be a PDF/i)
        expect(existsSync(join(home, '..', 'claude-was-called'))).toBe(true)
        expect(existsSync(join(home, 'profile', 'cv.md'))).toBe(false)
      })
    })

    it('says a missing file is missing', async () => {
      await withEmptyServer(async (server, home) => {
        await expect(server.call('draft_cv', { sources: [join(home, '..', 'nope.pdf')] })).rejects.toThrow(/no such file|not found|does not exist/i)
        expect(existsSync(join(home, '..', 'claude-was-called'))).toBe(false)
      })
    })

    it('refuses a file of another type', async () => {
      await withEmptyServer(async (server, home) => {
        const file = join(home, '..', 'run.exe')
        writeFileSync(file, 'MZ')
        await expect(server.call('draft_cv', { sources: [file] })).rejects.toThrow(/must be a PDF/i)
        expect(existsSync(join(home, 'profile', 'cv.md'))).toBe(false)
      })
    })
  })
})
