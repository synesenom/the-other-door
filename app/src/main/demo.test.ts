import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { JOBS_DATA_VERSION, PROFILE_DATA_VERSION } from './data-versions'
import { DEMO_JOBS, demoDir, demoEnv, demoMode, demoModeFor, demoRunMs, onboardDir, onboardEnv, onboardMode, onboardModeFor, resetOnboard, seedDemo } from './demo'

describe('demoMode', () => {
  it('reads the electron-vite mode: the demo kept, or built again', () => {
    expect(demoMode('demo')).toBe('keep')
    expect(demoMode('demo-fresh')).toBe('fresh')
    expect(demoMode('development')).toBeNull()
    expect(demoMode(undefined)).toBeNull()
  })
})

describe('demoDir', () => {
  it('is DOOR_DEMO_DIR when set, else app/.demo of the checkout', () => {
    expect(demoDir({}, '/repo')).toBe(join('/repo', 'app', '.demo'))
    expect(demoDir({ DOOR_DEMO_DIR: '' }, '/repo')).toBe(join('/repo', 'app', '.demo'))
    expect(demoDir({ DOOR_DEMO_DIR: '/tmp/x/demo' }, '/repo')).toBe('/tmp/x/demo')
  })

  it('an override at the checkout\'s real data is still refused', () => {
    const repo = mkdtempSync(join(tmpdir(), 'door-repo-'))
    for (const d of ['jobs', 'profile']) mkdirSync(join(repo, d))
    for (const where of [repo, join(repo, 'jobs'), join(repo, 'profile')]) {
      expect(() => seedDemo(demoDir({ DOOR_DEMO_DIR: where }, repo), repo, 'keep')).toThrow(/demo/)
    }
  })
})

describe('demoModeFor', () => {
  it('is the build mode, or DOOR_DEMO_DIR in a build that is not packaged', () => {
    expect(demoModeFor('demo', {}, false)).toBe('keep')
    expect(demoModeFor('production', { DOOR_DEMO_DIR: '/tmp/d' }, false)).toBe('keep')
    expect(demoModeFor(undefined, { DOOR_DEMO_DIR: '/tmp/d' }, false)).toBe('keep')
    expect(demoModeFor('production', { DOOR_DEMO_DIR: '/tmp/d' }, true)).toBeNull()
    expect(demoModeFor('production', {}, false)).toBeNull()
    expect(demoModeFor('demo-fresh', { DOOR_DEMO_DIR: '/tmp/d' }, false)).toBe('fresh')
  })
})

describe('demoRunMs', () => {
  it('reads DOOR_DEMO_RUN_MS as a positive number, else nothing', () => {
    expect(demoRunMs({ DOOR_DEMO_RUN_MS: '1500' })).toBe(1500)
    for (const bad of [undefined, '', 'x', '0', '-5']) expect(demoRunMs({ DOOR_DEMO_RUN_MS: bad })).toBeUndefined()
  })
})

describe('demoEnv', () => {
  it('points the data folder and the Drive state into the demo, and keeps HOME and PATH for claude', () => {
    const env = demoEnv({ HOME: '/Users/me', PATH: '/bin', DOOR_HOME: '/real' }, '/repo/app/.demo')
    expect(env).toMatchObject({
      HOME: '/Users/me',
      PATH: '/bin',
      DOOR_HOME: '/repo/app/.demo',
      XDG_CONFIG_HOME: join('/repo/app/.demo', '.config'),
      APPDATA: join('/repo/app/.demo', 'appdata'),
    })
  })
})

describe('seedDemo', () => {
  const repo = join(__dirname, '..', '..', '..')
  const now = new Date('2026-10-29T10:00:00Z')
  const fresh = () => join(mkdtempSync(join(tmpdir(), 'door-demo-')), '.demo')
  const postings = (demo: string) =>
    readdirSync(join(demo, 'jobs', 'postings'), { recursive: true })
      .map(String)
      .filter((f) => f.endsWith('.json'))
      .map((f) => JSON.parse(readFileSync(join(demo, 'jobs', 'postings', f), 'utf8')))

  it('with discovery off (the README GIF), the demo profile has every discovery source off', () => {
    const demo = fresh()
    seedDemo(demo, repo, 'keep', now, { discoveryOff: true })
    const config = JSON.parse(readFileSync(join(demo, 'profile', 'config.json'), 'utf8'))
    for (const key of ['linkedin_discovery', 'profession_discovery', 'hellowork_discovery', 'jobbsafari_discovery']) expect(config[key]).toBe(false)
  })

  it('stamps both folders with the data versions this build writes, so the first start upgrades nothing', () => {
    const demo = fresh()
    seedDemo(demo, repo, 'keep', now)
    expect(readFileSync(join(demo, 'profile', '.data_version'), 'utf8')).toBe(`${PROFILE_DATA_VERSION}\n`)
    expect(readFileSync(join(demo, 'jobs', '.data_version'), 'utf8')).toBe(`${JOBS_DATA_VERSION}\n`)
  })

  it('builds the example profile and made-up jobs in every state, dated from today', () => {
    const demo = fresh()
    expect(seedDemo(demo, repo, 'keep', now)).toEqual({ created: true })
    expect(JSON.parse(readFileSync(join(demo, 'profile', 'config.json'), 'utf8')).name).toBe('Jane Doe')
    // Not the example byte for byte, or Prepare would refuse it.
    expect(readFileSync(join(demo, 'profile', 'story_bank.md'), 'utf8')).not.toBe(readFileSync(join(repo, 'profile.example', 'story_bank.md'), 'utf8'))
    expect(readFileSync(join(demo, 'profile', 'cv.md'), 'utf8')).not.toBe(readFileSync(join(repo, 'profile.example', 'cv.md'), 'utf8'))
    const all = postings(demo)
    expect(all).toHaveLength(DEMO_JOBS.length)
    for (const p of all) {
      for (const key of ['id', 'title', 'company', 'location', 'url', 'description', 'posted_at', 'scraped_at', 'source', 'score']) expect(p, key).toHaveProperty(key)
      expect(p.url).toMatch(/^https:\/\/example\.com\//)
    }
    expect(all.some((p) => p.title_en)).toBe(true)
    const ledger = JSON.parse(readFileSync(join(demo, 'jobs', 'applications.json'), 'utf8'))
    const statuses = Object.values(ledger).map((e) => (e as { status: string }).status)
    for (const s of ['prepared', 'applied', 'interview:screening', 'discarded']) expect(statuses).toContain(s)
    const prepared = Object.keys(ledger).find((id) => ledger[id].status === 'prepared')!
    expect(existsSync(join(demo, 'jobs', 'output', prepared, 'cv.pdf'))).toBe(true)
    expect(existsSync(join(demo, 'jobs', 'output', prepared, 'cover_letter_page_1.png'))).toBe(true)
    expect(existsSync(join(demo, 'jobs', 'output', prepared, 'sent'))).toBe(false)
    // A sent application has its files and the copy kept when it went out, as `jobs status` leaves it.
    for (const id of Object.keys(ledger).filter((id) => ['applied', 'interview:screening'].includes(ledger[id].status))) {
      expect(existsSync(join(demo, 'jobs', 'output', id, 'cv.pdf')), id).toBe(true)
      expect(existsSync(join(demo, 'jobs', 'output', id, 'sent', 'cv.pdf')), id).toBe(true)
      expect(existsSync(join(demo, 'jobs', 'output', id, 'sent', 'cover_letter_page_1.png')), id).toBe(true)
    }
    // Some are new since the last review: it was stamped yesterday, they were seen today.
    const reviewed = JSON.parse(readFileSync(join(demo, 'jobs', 'last_review.json'), 'utf8')).reviewed_at
    expect(all.filter((p) => p.scraped_at > reviewed).length).toBeGreaterThan(0)
    expect(all.filter((p) => p.scraped_at <= reviewed).length).toBeGreaterThan(0)
    // Analytics has figures: a week of made-up Claude calls, each weighed, all within the last 7 days.
    const usage = readFileSync(join(demo, 'jobs', 'usage.jsonl'), 'utf8').trim().split('\n').map((l) => JSON.parse(l))
    expect(new Set(usage.map((l) => l.feature))).toEqual(new Set(['match_scoring', 'title_translation', 'tailoring', 'revise', 'salary']))
    expect(usage.every((l) => l.weight > 0 && now.getTime() - Date.parse(l.at) < 7 * 86_400_000)).toBe(true)
  })

  it('keeps your changes on the next start, and fresh builds it again', () => {
    const demo = fresh()
    seedDemo(demo, repo, 'keep', now)
    writeFileSync(join(demo, 'jobs', 'applications.json'), '{"changed": true}')
    expect(seedDemo(demo, repo, 'keep', now)).toEqual({ created: false })
    expect(readFileSync(join(demo, 'jobs', 'applications.json'), 'utf8')).toContain('changed')
    expect(seedDemo(demo, repo, 'fresh', now)).toEqual({ created: true })
    expect(readFileSync(join(demo, 'jobs', 'applications.json'), 'utf8')).not.toContain('changed')
  })
})

describe('seedDemo refuses', () => {
  it('a demo folder that is the checkout or its real data, before touching anything', () => {
    // A throwaway stand-in for the checkout: a refusal must come before any delete.
    const repo = mkdtempSync(join(tmpdir(), 'door-repo-'))
    for (const d of ['jobs', 'profile']) mkdirSync(join(repo, d))
    writeFileSync(join(repo, 'jobs', 'applications.json'), '{}')
    for (const bad of [repo, join(repo, 'jobs'), join(repo, 'profile'), join(repo, 'jobs', 'x')]) {
      expect(() => seedDemo(bad, repo, 'fresh')).toThrow(/demo/)
    }
    expect(existsSync(join(repo, 'jobs', 'applications.json'))).toBe(true)
  })
})

describe('the onboarding sandbox', () => {
  it('onboardMode reads the electron-vite mode', () => {
    expect(onboardMode('onboard')).toBeTruthy()
    expect(onboardMode('demo')).toBeNull()
    expect(onboardMode(undefined)).toBeNull()
  })

  it('onboardDir is DOOR_ONBOARD_DIR when set, else app/.onboard of the checkout', () => {
    expect(onboardDir({}, '/repo')).toBe(join('/repo', 'app', '.onboard'))
    expect(onboardDir({ DOOR_ONBOARD_DIR: '' }, '/repo')).toBe(join('/repo', 'app', '.onboard'))
    expect(onboardDir({ DOOR_ONBOARD_DIR: '/tmp/o' }, '/repo')).toBe('/tmp/o')
  })

  it('onboardModeFor honours DOOR_ONBOARD_DIR only in a build that is not packaged', () => {
    expect(onboardModeFor('onboard', {}, true)).toBeTruthy()
    expect(onboardModeFor('production', { DOOR_ONBOARD_DIR: '/tmp/o' }, false)).toBeTruthy()
    expect(onboardModeFor('production', { DOOR_ONBOARD_DIR: '/tmp/o' }, true)).toBeNull()
    expect(onboardModeFor('production', {}, false)).toBeNull()
  })

  it('resetOnboard leaves an empty folder, whatever was there', () => {
    const repo = join(__dirname, '..', '..', '..')
    const dir = join(mkdtempSync(join(tmpdir(), 'door-onboard-')), '.onboard')
    mkdirSync(join(dir, 'profile'), { recursive: true })
    writeFileSync(join(dir, 'profile', 'config.json'), '{}')
    resetOnboard(dir, repo)
    expect(existsSync(dir)).toBe(true)
    expect(readdirSync(dir)).toEqual([])
  })

  it('resetOnboard refuses the checkout, jobs/ and profile/ before deleting anything', () => {
    const repo = mkdtempSync(join(tmpdir(), 'door-repo-'))
    for (const d of ['jobs', 'profile']) mkdirSync(join(repo, d))
    writeFileSync(join(repo, 'jobs', 'applications.json'), '{}')
    for (const bad of [repo, join(repo, 'jobs'), join(repo, 'profile'), join(repo, 'jobs', 'x')]) {
      expect(() => resetOnboard(bad, repo)).toThrow(/onboarding/)
    }
    expect(existsSync(join(repo, 'jobs', 'applications.json'))).toBe(true)
  })

  it('onboardEnv is the demo env, plus an isolated Claude config only when asked to be signed out', () => {
    const base = { HOME: '/Users/me', PATH: '/bin' }
    expect(onboardEnv(base, '/o')).toEqual(demoEnv(base, '/o'))
    expect(onboardEnv(base, '/o')).not.toHaveProperty('CLAUDE_CONFIG_DIR')
    expect(onboardEnv({ ...base, DOOR_ONBOARD_SIGNED_OUT: '1' }, '/o')).toMatchObject({ CLAUDE_CONFIG_DIR: join('/o', '.claude') })
  })
})
