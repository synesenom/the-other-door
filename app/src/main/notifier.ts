// Shows a notice as a system notification, only while the window is not in front, and sends the
// click to the window. Everything electron is injected (the class, focus, send), so this file
// imports nothing from it and a test drives it with fakes.
import type { Notice, NoticeTarget } from './notices'

/** Pushed to the window when a notification is clicked; src/preload/index.ts repeats the literal. */
export const CHANNEL_OPEN = 'door:open'

const DEDUP_MS = 5_000

interface NotificationLike {
  on(event: 'click', listener: () => void): unknown
  show(): void
}
interface NotificationClass {
  new (options: { title: string; body: string }): NotificationLike
  isSupported(): boolean
}

export function createNotifier(deps: {
  Notification: NotificationClass
  isFocused: () => boolean
  focusWindow: () => void
  send: (channel: string, target: NoticeTarget) => void
  now?: () => number
}): (notice: Notice | null) => void {
  const now = deps.now ?? Date.now
  const recent = new Map<string, number>()
  return (notice) => {
    if (!notice) return
    try {
      if (deps.isFocused() || !deps.Notification.isSupported()) return
      const key = `${notice.title}|${notice.body}`
      const t = now()
      const last = recent.get(key)
      if (last !== undefined && t - last < DEDUP_MS) return
      recent.set(key, t)
      for (const [k, at] of recent) if (t - at >= DEDUP_MS) recent.delete(k)
      const n = new deps.Notification({ title: notice.title, body: notice.body })
      n.on('click', () => {
        deps.focusWindow()
        deps.send(CHANNEL_OPEN, notice.target)
      })
      n.show()
    } catch {
      // a notification is a courtesy: never let it break a call
    }
  }
}
