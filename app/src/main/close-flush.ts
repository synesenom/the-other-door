// Closing the window (or quitting) gives the page a moment to write what it holds unsaved (the Master CV's last
// seconds of typing): the page is asked, answers when done, and the close goes on after at most FLUSH_TIMEOUT_MS.
export const FLUSH_TIMEOUT_MS = 3000

export interface FlushTarget {
  send(channel: string): void
  isDestroyed(): boolean
}
export interface FlushIpc {
  once(channel: string, cb: () => void): void
  removeListener(channel: string, cb: () => void): void
}

/** Asks the page to write what is pending; resolves when it says so, or after `timeoutMs`. Never rejects. */
export function flushPage(target: FlushTarget, ipc: FlushIpc, timeoutMs = FLUSH_TIMEOUT_MS): Promise<void> {
  if (target.isDestroyed()) return Promise.resolve()
  return new Promise((resolve) => {
    const done = () => {
      clearTimeout(timer)
      ipc.removeListener('door:before-close-done', done)
      resolve()
    }
    const timer = setTimeout(done, timeoutMs)
    ipc.once('door:before-close-done', done)
    try {
      target.send('door:before-close')
    } catch {
      done()
    }
  })
}
