import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { JOBS_DATA_VERSION, PROFILE_DATA_VERSION } from './data-versions'
import { DEMO_JOBS, seedSandbox } from './sandbox'

describe('seedSandbox', () => {
  const repo = join(__dirname, '..', '..', '..')
  const now = new Date('2026-10-29T10:00:00Z')
  const fresh = () => join(mkdtempSync(join(tmpdir(), 'door-sandbox-')), '.sandbox')
  const postings = (demo: string) =>
    readdirSync(join(demo, 'jobs', 'postings'), { recursive: true })
      .map(String)
      .filter((f) => f.endsWith('.json'))
      .map((f) => JSON.parse(readFileSync(join(demo, 'jobs', 'postings', f), 'utf8')))

  it('with discovery off (the README GIF), the sandbox profile has every discovery source off', () => {
    const demo = fresh()
    seedSandbox(demo, repo, false, now, { discoveryOff: true })
    const config = JSON.parse(readFileSync(join(demo, 'profile', 'config.json'), 'utf8'))
    for (const key of ['linkedin_discovery', 'profession_discovery', 'hellowork_discovery', 'jobbsafari_discovery']) expect(config[key]).toBe(false)
  })

  it('stamps both folders with the data versions this build writes, so the first start upgrades nothing', () => {
    const demo = fresh()
    seedSandbox(demo, repo, false, now)
    expect(readFileSync(join(demo, 'profile', '.data_version'), 'utf8')).toBe(`${PROFILE_DATA_VERSION}\n`)
    expect(readFileSync(join(demo, 'jobs', '.data_version'), 'utf8')).toBe(`${JOBS_DATA_VERSION}\n`)
  })

  it('builds the example profile and made-up jobs in every state, dated from today', () => {
    const demo = fresh()
    expect(seedSandbox(demo, repo, false, now)).toEqual({ created: true })
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
    seedSandbox(demo, repo, false, now)
    writeFileSync(join(demo, 'jobs', 'applications.json'), '{"changed": true}')
    expect(seedSandbox(demo, repo, false, now)).toEqual({ created: false })
    expect(readFileSync(join(demo, 'jobs', 'applications.json'), 'utf8')).toContain('changed')
    expect(seedSandbox(demo, repo, true, now)).toEqual({ created: true })
    expect(readFileSync(join(demo, 'jobs', 'applications.json'), 'utf8')).not.toContain('changed')
  })
})

describe('seedSandbox refuses', () => {
  it('a sandbox folder that is the checkout or its real data, before touching anything', () => {
    // A throwaway stand-in for the checkout: a refusal must come before any delete.
    const repo = mkdtempSync(join(tmpdir(), 'door-repo-'))
    for (const d of ['jobs', 'profile']) mkdirSync(join(repo, d))
    writeFileSync(join(repo, 'jobs', 'applications.json'), '{}')
    for (const bad of [repo, join(repo, 'jobs'), join(repo, 'profile'), join(repo, 'jobs', 'x')]) {
      expect(() => seedSandbox(bad, repo, true)).toThrow(/sandbox/)
    }
    expect(existsSync(join(repo, 'jobs', 'applications.json'))).toBe(true)
  })
})
