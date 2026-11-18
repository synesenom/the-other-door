import { EventEmitter } from 'node:events'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { beforeQuitStep, closeStep, flushPage } from './close-flush'
import { beforeCloseHandler } from '../preload/before-close'

afterEach(() => vi.useRealTimers())

const page = () => ({ send: vi.fn(), isDestroyed: () => false })
const ipcOf = (e: EventEmitter) => ({ on: e.on.bind(e), removeListener: e.removeListener.bind(e) })

describe('flushPage', () => {
  it('asks the page and waits for its answer', async () => {
    const e = new EventEmitter()
    const target = page()
    let resolved = false
    const p = flushPage(target, ipcOf(e)).then(() => (resolved = true))
    expect(target.send).toHaveBeenCalledWith('door:before-close')
    await Promise.resolve()
    expect(resolved).toBe(false)
    e.emit('door:before-close-done', { sender: target })
    await p
    expect(resolved).toBe(true)
    expect(e.listenerCount('door:before-close-done')).toBe(0)
  })

  it('ignores another page\'s answer', async () => {
    const e = new EventEmitter()
    const target = page()
    let resolved = false
    const p = flushPage(target, ipcOf(e)).then(() => (resolved = true))
    e.emit('door:before-close-done', { sender: page() })
    await Promise.resolve()
    expect(resolved).toBe(false)
    e.emit('door:before-close-done', { sender: target })
    await p
  })

  it('goes on after the timeout when the page never answers', async () => {
    vi.useFakeTimers()
    const e = new EventEmitter()
    const p = flushPage(page(), ipcOf(e), 3000)
    await vi.advanceTimersByTimeAsync(3000)
    await p
    expect(e.listenerCount('door:before-close-done')).toBe(0)
  })

  it('does not wait for a page that is gone', async () => {
    const send = vi.fn()
    await flushPage({ send, isDestroyed: () => true }, ipcOf(new EventEmitter()))
    expect(send).not.toHaveBeenCalled()
  })
})

describe('the close and quit steps', () => {
  it('a window close is held once for the flush, then let through', () => {
    expect(closeStep({ closing: false, pagesFlushed: false })).toBe('flush-first')
    expect(closeStep({ closing: true, pagesFlushed: false })).toBe('let-close')
  })

  it('a quit flushes the pages first (before the update stop and the server end), and its windows then close without another hold', () => {
    expect(beforeQuitStep({ pagesFlushed: false })).toBe('flush-then-quit')
    expect(beforeQuitStep({ pagesFlushed: true })).toBe('go-on')
    expect(closeStep({ closing: false, pagesFlushed: true })).toBe('let-close')
  })
})

describe('the page\'s answer (preload)', () => {
  it('answers at once when nothing is registered', async () => {
    const answer = vi.fn()
    beforeCloseHandler([], answer)()
    await Promise.resolve()
    await Promise.resolve()
    expect(answer).toHaveBeenCalledTimes(1)
  })

  it('answers only after the writers settled, a rejection and a throw included', async () => {
    let finish: () => void = () => undefined
    const slow = () => new Promise<void>((r) => (finish = r))
    const answer = vi.fn()
    beforeCloseHandler([slow, () => Promise.reject(new Error('x')), () => { throw new Error('y') }], answer)()
    await new Promise((r) => setTimeout(r, 10))
    expect(answer).not.toHaveBeenCalled()
    finish()
    await vi.waitFor(() => expect(answer).toHaveBeenCalledTimes(1))
  })
})
