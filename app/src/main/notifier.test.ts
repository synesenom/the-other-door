import { describe, expect, it, vi } from 'vitest'
import { CHANNEL_OPEN, createNotifier } from './notifier'
import type { Notice } from './notices'

const notice = (over: Partial<Notice> = {}): Notice => ({ title: 'New jobs found', body: '3 new matches', target: { screen: 'matches', newOnly: true }, ...over })

function setup(over: { focused?: boolean; supported?: boolean; throwOnShow?: boolean } = {}) {
  const shown: { title: string; body: string; show: ReturnType<typeof vi.fn<() => void>>; click?: () => void }[] = []
  class FakeNotification {
    static isSupported() {
      return over.supported ?? true
    }
    record: (typeof shown)[number]
    constructor(opts: { title: string; body: string }) {
      this.record = { ...opts, show: vi.fn<() => void>(() => { if (over.throwOnShow) throw new Error('boom') }) }
      shown.push(this.record)
    }
    on(event: string, cb: () => void) {
      if (event === 'click') this.record.click = cb
    }
    show() {
      this.record.show()
    }
  }
  let t = 1_000_000
  const focusWindow = vi.fn()
  const send = vi.fn()
  const notify = createNotifier({ Notification: FakeNotification, isFocused: () => over.focused ?? false, focusWindow, send, now: () => t })
  return { notify, shown, focusWindow, send, advance: (ms: number) => (t += ms) }
}

describe('createNotifier', () => {
  it('names the channel', () => {
    expect(CHANNEL_OPEN).toBe('door:open')
  })
  it('shows nothing while the window is focused', () => {
    const { notify, shown } = setup({ focused: true })
    notify(notice())
    expect(shown).toHaveLength(0)
  })
  it('shows one notification while unfocused', () => {
    const { notify, shown } = setup()
    notify(notice())
    expect(shown).toHaveLength(1)
    expect(shown[0]).toMatchObject({ title: 'New jobs found', body: '3 new matches' })
    expect(shown[0].show).toHaveBeenCalledTimes(1)
  })
  it('shows nothing when notifications are not supported', () => {
    const { notify, shown } = setup({ supported: false })
    notify(notice())
    expect(shown).toHaveLength(0)
  })
  it('a click brings the window forward and sends the target', () => {
    const { notify, shown, focusWindow, send } = setup()
    notify(notice())
    shown[0].click!()
    expect(focusWindow).toHaveBeenCalledTimes(1)
    expect(send).toHaveBeenCalledWith('door:open', { screen: 'matches', newOnly: true })
  })
  it('drops an identical notice within 5 s, not one after, not a different one', () => {
    const { notify, shown, advance } = setup()
    notify(notice())
    advance(4_000)
    notify(notice())
    expect(shown).toHaveLength(1)
    notify(notice({ title: 'Ad imported' }))
    expect(shown).toHaveLength(2)
    advance(5_000)
    notify(notice())
    expect(shown).toHaveLength(3)
  })
  it('ignores null', () => {
    const { notify, shown } = setup()
    notify(null)
    expect(shown).toHaveLength(0)
  })
  it('swallows a failure to show', () => {
    const { notify } = setup({ throwOnShow: true })
    expect(() => notify(notice())).not.toThrow()
  })
})
