import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { foldBoard, watchRunBoard, type RunBoard } from './run-board'

const STEPS = [
  { name: 'search', status: 'done', detail: '12 postings', started_at: '2026-10-29T08:00:00+00:00', finished_at: '2026-10-29T08:01:00+00:00', sites: { jobindex: 12 } },
  { name: 'collect', status: 'running', detail: '', done: 3, total: 9, hosts: ['a.example'] },
]
const progress = { message: 'collect: 3/9', steps: STEPS, pid: 4242 }
const lock = { pid: 4242, purpose: 'run', started_at: '2026-10-29T08:00:00+00:00' }

describe('foldBoard', () => {
  it('is inactive without a lock, or when its process is gone', () => {
    expect(foldBoard(progress, null, () => true)).toEqual({ active: false })
    expect(foldBoard(progress, lock, () => false)).toEqual({ active: false })
    expect(foldBoard(null, lock, () => true)).toEqual({ active: false })
    expect(foldBoard(progress, { purpose: 'run' }, () => true)).toEqual({ active: false })
  })

  it('is the run while the lock holder is alive', () => {
    expect(foldBoard(progress, lock, () => true)).toEqual({
      active: true,
      own: false,
      started_at: lock.started_at,
      purpose: 'run',
      message: 'collect: 3/9',
      steps: STEPS,
    })
  })

  it('is own when the lock holder is the app\'s server', () => {
    const alive = vi.fn(() => true)
    expect(foldBoard(progress, lock, alive, () => 4242)).toMatchObject({ active: true, own: true })
    expect(foldBoard(progress, lock, alive, () => 7)).toMatchObject({ own: false })
    expect(alive).toHaveBeenCalledWith(4242)
  })

  it('reads missing or malformed steps as none', () => {
    for (const steps of [undefined, null, 'x', { a: 1 }]) {
      expect(foldBoard({ message: 'm', steps }, lock, () => true)).toMatchObject({ active: true, steps: [] })
    }
    const odd = foldBoard({ message: 'm', steps: [{ name: 'search', status: 'running' }, 3, { status: 'x' }] }, lock, () => true)
    expect(odd).toMatchObject({ steps: [{ name: 'search', status: 'running' }] })
  })
})

describe('watchRunBoard', () => {
  let home: string
  let stop: (() => void) | null = null
  beforeEach(() => {
    vi.useFakeTimers()
    home = mkdtempSync(join(tmpdir(), 'run-board-'))
    mkdirSync(join(home, 'jobs'))
  })
  afterEach(() => {
    stop?.()
    stop = null
    vi.useRealTimers()
    rmSync(home, { recursive: true, force: true })
  })
  const put = (name: string, value: unknown) => writeFileSync(join(home, 'jobs', name), JSON.stringify(value))

  it('pushes the board once when the files appear, and inactive when they go', async () => {
    vi.useRealTimers() // a real file event needs real time
    const seen: RunBoard[] = []
    // a long poll: only the file watch can find it within the wait
    stop = watchRunBoard(home, (b) => seen.push(b), { alive: () => true, debounceMs: 30, pollMs: 60_000 }).stop
    expect(seen).toEqual([])
    put('.lock.json', lock)
    put('.progress.json', progress)
    await vi.waitFor(() => expect(seen.filter((b) => b.active)).toHaveLength(1), { timeout: 3000 })
    expect(seen.filter((b) => b.active)[0]).toMatchObject({ started_at: lock.started_at, message: 'collect: 3/9' })
    rmSync(join(home, 'jobs', '.progress.json'))
    rmSync(join(home, 'jobs', '.lock.json'))
    await vi.waitFor(() => expect(seen[seen.length - 1]).toEqual({ active: false }), { timeout: 3000 })
  })

  it('pushes only when the board changed', async () => {
    const seen: RunBoard[] = []
    stop = watchRunBoard(home, (b) => seen.push(b), { alive: () => true, debounceMs: 10, pollMs: 100 }).stop
    put('.lock.json', lock)
    put('.progress.json', progress)
    await vi.advanceTimersByTimeAsync(1000)
    const n = seen.length
    await vi.advanceTimersByTimeAsync(1000)
    expect(seen).toHaveLength(n)
    put('.progress.json', { ...progress, message: 'collect: 4/9' })
    await vi.advanceTimersByTimeAsync(1000)
    expect(seen[seen.length - 1]).toMatchObject({ message: 'collect: 4/9' })
  })

  it('catches a change by polling when no file event comes', async () => {
    const seen: RunBoard[] = []
    // a missing jobs folder cannot be watched: only the poll finds the files
    const lonely = mkdtempSync(join(tmpdir(), 'run-board-'))
    const w = watchRunBoard(lonely, (b) => seen.push(b), { alive: () => true, debounceMs: 10, pollMs: 500 })
    mkdirSync(join(lonely, 'jobs'))
    writeFileSync(join(lonely, 'jobs', '.lock.json'), JSON.stringify(lock))
    writeFileSync(join(lonely, 'jobs', '.progress.json'), JSON.stringify(progress))
    await vi.advanceTimersByTimeAsync(1100)
    w.stop()
    rmSync(lonely, { recursive: true, force: true })
    expect(seen.some((b) => b.active)).toBe(true)
  })

  it('current() is the last board, and stop() ends watching', async () => {
    const seen: RunBoard[] = []
    const w = watchRunBoard(home, (b) => seen.push(b), { alive: () => true, debounceMs: 10, pollMs: 100 })
    put('.lock.json', lock)
    put('.progress.json', progress)
    await vi.advanceTimersByTimeAsync(500)
    expect(w.current()).toMatchObject({ active: true })
    w.stop()
    const n = seen.length
    put('.progress.json', { ...progress, message: 'later' })
    await vi.advanceTimersByTimeAsync(2000)
    expect(seen).toHaveLength(n)
  })
})
