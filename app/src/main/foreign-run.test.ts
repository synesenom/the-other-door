import { describe, expect, it, vi } from 'vitest'
import { foreignRunEnded, watchForeignEnd } from './foreign-run'
import type { RunBoard } from './run-board'

const active = (over: Record<string, unknown> = {}): RunBoard => ({ active: true, own: false, started_at: '2026-10-29T08:00:00', purpose: 'find', message: '', steps: [], ...over }) as RunBoard
const idle: RunBoard = { active: false }

describe('foreignRunEnded', () => {
  it('is the start of a run that was not ours and is over', () => {
    expect(foreignRunEnded(active(), idle)).toEqual({ startedAt: '2026-10-29T08:00:00' })
  })
  it('is nothing for our own run, the demo, a run going on or nothing before', () => {
    expect(foreignRunEnded(active({ own: true }), idle)).toBeNull()
    expect(foreignRunEnded(active({ demo: true }), idle)).toBeNull()
    expect(foreignRunEnded(active(), active())).toBeNull()
    expect(foreignRunEnded(idle, idle)).toBeNull()
    expect(foreignRunEnded(idle, active())).toBeNull()
  })
})

describe('watchForeignEnd', () => {
  const summary = (last_run: unknown) => ({ since_last_review: { last_run } })
  it('announces once per ending, with the count from the fresh record', async () => {
    const call = vi.fn(async () => summary({ started_at: '2026-10-29T08:00:03', new_above_threshold: 4 }))
    const notify = vi.fn()
    const onBoard = watchForeignEnd({ call }, notify)
    await onBoard(idle)
    await onBoard(active())
    await onBoard(active())
    expect(notify).not.toHaveBeenCalled()
    await onBoard(idle)
    await onBoard(idle)
    expect(call).toHaveBeenCalledWith('status_summary', {})
    expect(notify).toHaveBeenCalledTimes(1)
    expect(notify.mock.calls[0][0]).toEqual({ title: 'A run finished', body: '4 new matches', target: { screen: 'matches', newOnly: true } })
  })
  it('a failing summary still announces, without a count', async () => {
    const notify = vi.fn()
    const onBoard = watchForeignEnd({ call: async () => { throw new Error('busy') } }, notify)
    await onBoard(active())
    await onBoard(idle)
    expect(notify).toHaveBeenCalledTimes(1)
    expect(notify.mock.calls[0][0].body).not.toMatch(/\d/)
  })
  it('a stale record gives no count', async () => {
    const notify = vi.fn()
    const onBoard = watchForeignEnd({ call: async () => summary({ started_at: '2026-10-01T08:00:00', new_above_threshold: 9 }) }, notify)
    await onBoard(active())
    await onBoard(idle)
    expect(notify.mock.calls[0][0].body).not.toMatch(/\d/)
  })
})
