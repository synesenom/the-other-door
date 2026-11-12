import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { startDemoRun, type DemoRunRecord } from './demo-run'
import { type RunBoard } from './run-board'

const NOW = new Date('2026-10-29T08:00:00.000Z')
let dir: string
beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
  dir = mkdtempSync(join(tmpdir(), 'demo-run-'))
})
afterEach(() => {
  vi.useRealTimers()
  rmSync(dir, { recursive: true, force: true })
})

const postingFiles = () => {
  const root = join(dir, 'jobs', 'postings')
  if (!existsSync(root)) return []
  return readdirSync(root, { recursive: true, encoding: 'utf8' }).filter((f) => f.endsWith('.json'))
}

function start(args: Record<string, unknown> = {}) {
  const boards: RunBoard[] = []
  const lines: string[] = []
  const run = startDemoRun(dir, { args, onBoard: (b) => boards.push(b), onProgress: (p) => lines.push(p.message) })
  const result = run.result.then((r) => ({ r }), (e) => ({ e }))
  return { run, boards, lines, result }
}

describe('startDemoRun', () => {
  it('plays the five steps in order in about twenty seconds', async () => {
    const { boards, lines, result } = start()
    await vi.advanceTimersByTimeAsync(0)
    const first = boards[0]
    expect(first).toMatchObject({ active: true, own: true, demo: true, purpose: 'run' })
    if (!first.active || !boards[1].active) throw new Error('inactive')
    expect(first.steps.map((s) => s.status)).toEqual(['waiting', 'waiting', 'waiting', 'waiting', 'waiting'])
    expect(boards[1].steps.map((s) => [s.name, s.status])).toEqual([
      ['search', 'waiting'], ['discover', 'running'], ['follow', 'waiting'], ['collect', 'waiting'], ['match', 'waiting'],
    ])
    expect(boards[2].active && boards[2].steps.map((s) => s.status).slice(0, 2)).toEqual(['running', 'running']) // discover works beside search
    await vi.advanceTimersByTimeAsync(21_000)
    expect('r' in (await result)).toBe(true)

    const finished: string[] = []
    for (const b of boards) {
      if (!b.active) continue
      for (const s of b.steps) if (s.status === 'done' && !finished.includes(s.name)) finished.push(s.name)
    }
    expect(finished).toEqual(['search', 'discover', 'follow', 'collect', 'match'])
    const last = boards[boards.length - 1]
    expect(last).toEqual({ active: false })
    expect(lines.length).toBeGreaterThan(5)
    // a running step shows its work: sites for search, a count for collect
    const searching = boards.flatMap((b) => (b.active ? b.steps : [])).find((s) => s.name === 'search' && s.sites)
    expect(searching?.sites).toBeTruthy()
    const collecting = boards.flatMap((b) => (b.active ? b.steps : [])).find((s) => s.name === 'collect' && s.status === 'running' && s.total)
    expect(collecting).toMatchObject({ total: expect.any(Number) })
  })

  it('writes exactly two new postings and a record that says so', async () => {
    const { result } = start()
    expect(postingFiles()).toEqual([])
    await vi.advanceTimersByTimeAsync(21_000)
    const { r } = (await result) as { r: DemoRunRecord }
    const files = postingFiles()
    expect(files).toHaveLength(2)
    expect(files.every((f) => f.startsWith('2026-10-29'))).toBe(true)
    const posts = files.map((f) => JSON.parse(readFileSync(join(dir, 'jobs', 'postings', f), 'utf8')))
    expect(posts.map((p) => p.score).sort()).toEqual([0.73, 0.86])
    for (const p of posts) expect(p.scraped_at).toBe(NOW.toISOString())

    expect(r.new_above_threshold).toHaveLength(2)
    expect(r.top.map((t) => t.id).sort()).toEqual(posts.map((p) => p.id).sort())
    expect(r.started_at).toBe(NOW.toISOString())
    expect(r.finished_at).toBeTruthy()
    expect(r.failures).toEqual([])
    const outcomes = Object.fromEntries(r.search!.sites.map((s) => [s.site, s]))
    expect(Object.values(outcomes).map((s) => s.outcome).sort()).toEqual(['empty', 'ok', 'resting'])
    expect(Object.values(outcomes).find((s) => s.outcome === 'resting')?.until).toBeTruthy()
    // the record is on disk where "Show run record" looks
    expect(existsSync(join(dir, 'jobs', 'runs', '2026-10-29T08-00-00-000Z.json'))).toBe(true)
  })

  it('reads the boards at once, each checked as it answers, and the source after them', async () => {
    const { boards } = start()
    await vi.advanceTimersByTimeAsync(21_000)
    const steps = (name: string) => boards.flatMap((b) => (b.active ? b.steps.filter((s) => s.name === name && s.status === 'running') : []))
    const search = steps('search')
    expect(search.some((s) => (s.items ?? []).filter((i) => i.state === 'running').length > 1)).toBe(true)
    const order: string[] = []
    for (const s of search) for (const i of s.items ?? []) if (i.state === 'done' && !order.includes(i.id)) order.push(i.id)
    expect(order[0]).toBe('thehub') // not the first listed: the quickest to answer
    expect(order).toHaveLength(8)
    const discover = steps('discover')
    expect(discover.at(-1)?.items?.map((i) => i.state)).toEqual(['done'])
  })

  it('skips the steps it is told to skip', async () => {
    const { boards, result } = start({ skip: ['discover'] })
    await vi.advanceTimersByTimeAsync(21_000)
    const { r } = (await result) as { r: DemoRunRecord }
    expect(r.skipped).toEqual({ discover: '--skip' })
    expect(r.steps).not.toContain('discover')
    const row = boards.flatMap((b) => (b.active ? b.steps : [])).find((s) => s.name === 'discover')
    expect(row).toMatchObject({ status: 'skipped' })
  })

  it('skips Discover, as a real run does, when the demo profile has every discovery source off', async () => {
    mkdirSync(join(dir, 'profile'), { recursive: true })
    writeFileSync(join(dir, 'profile', 'config.json'), JSON.stringify({ name: 'Jane Doe', linkedin_discovery: false, profession_discovery: false }))
    const { boards, lines, result } = start()
    await vi.advanceTimersByTimeAsync(21_000)
    const { r } = (await result) as { r: DemoRunRecord }
    expect(r.skipped).toEqual({ discover: 'linkedin_discovery is off; profession_discovery is off' })
    const row = boards.flatMap((b) => (b.active ? b.steps : [])).find((s) => s.name === 'discover')
    expect(row).toMatchObject({ status: 'skipped', detail: 'linkedin_discovery is off; profession_discovery is off' })
    expect(lines.some((l) => /LinkedIn|profession/.test(l))).toBe(false)
  })

  it('runs on an empty folder with the onboarding skips and leaves postings and a record', async () => {
    const { result } = start({ skip: ['discover', 'follow', 'collect'] })
    await vi.advanceTimersByTimeAsync(21_000)
    const { r } = (await result) as { r: DemoRunRecord }
    expect(r.steps).toEqual(['search', 'match'])
    expect(r.skipped).toEqual({ discover: '--skip', follow: '--skip', collect: '--skip' })
    expect(postingFiles().length).toBeGreaterThan(0)
    expect(readdirSync(join(dir, 'jobs', 'runs')).some((f) => f.endsWith('.json'))).toBe(true)
  })

  it('stop() cancels: nothing is written and the result rejects as stopped', async () => {
    const { run, boards, result } = start()
    await vi.advanceTimersByTimeAsync(8_000)
    run.stop()
    await vi.advanceTimersByTimeAsync(30_000)
    const out = (await result) as { e: { stopped?: boolean; message: string } }
    expect(out.e).toMatchObject({ message: 'stopped', stopped: true })
    expect(postingFiles()).toEqual([])
    expect(existsSync(join(dir, 'jobs', 'runs'))).toBe(false)
    expect(boards[boards.length - 1]).toEqual({ active: false })
  })

  it('the speed can be changed for a test (total milliseconds)', async () => {
    const boards: RunBoard[] = []
    const run = startDemoRun(dir, { args: {}, totalMs: 2000, onBoard: (b) => boards.push(b), onProgress: () => {} })
    await vi.advanceTimersByTimeAsync(2100)
    await expect(run.result).resolves.toBeTruthy()
  })
})
