import { EventEmitter } from 'node:events'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPage } from './close-flush'

afterEach(() => vi.useRealTimers())

describe('flushPage', () => {
  it('asks the page and waits for its answer', async () => {
    const ipc = new EventEmitter()
    const send = vi.fn()
    let resolved = false
    const p = flushPage({ send, isDestroyed: () => false }, ipc).then(() => (resolved = true))
    expect(send).toHaveBeenCalledWith('door:before-close')
    await Promise.resolve()
    expect(resolved).toBe(false)
    ipc.emit('door:before-close-done')
    await p
    expect(resolved).toBe(true)
    expect(ipc.listenerCount('door:before-close-done')).toBe(0)
  })

  it('goes on after the timeout when the page never answers', async () => {
    vi.useFakeTimers()
    const ipc = new EventEmitter()
    const p = flushPage({ send: vi.fn(), isDestroyed: () => false }, ipc, 3000)
    await vi.advanceTimersByTimeAsync(3000)
    await p
    expect(ipc.listenerCount('door:before-close-done')).toBe(0)
  })

  it('does not wait for a page that is gone', async () => {
    const send = vi.fn()
    await flushPage({ send, isDestroyed: () => true }, new EventEmitter())
    expect(send).not.toHaveBeenCalled()
  })
})
