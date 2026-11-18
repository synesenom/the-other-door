// Closing the window (or quitting) gives the page a moment to write what it holds unsaved (the Master CV's last
// seconds of typing): the page is asked, answers when done, and the close goes on after at most FLUSH_TIMEOUT_MS.
// A save that takes longer than that is cut off with the window: the text typed in that last moment can be lost.
const FLUSH_TIMEOUT_MS = 3000

export interface FlushTarget {
  send(channel: string): void
  isDestroyed(): boolean
}
export interface FlushIpc {
  on(channel: string, cb: (event: { sender: unknown }) => void): void
  removeListener(channel: string, cb: (event: { sender: unknown }) => void): void
}

/** Asks the page to write what is pending; resolves when that page says so, or after `timeoutMs`. Never rejects. */
export function flushPage(target: FlushTarget, ipc: FlushIpc, timeoutMs = FLUSH_TIMEOUT_MS): Promise<void> {
  if (target.isDestroyed()) return Promise.resolve()
  return new Promise((resolve) => {
    const onAnswer = (event: { sender: unknown }) => {
      if (event.sender === target) done()
    }
    const done = () => {
      clearTimeout(timer)
      ipc.removeListener('door:before-close-done', onAnswer)
      resolve()
    }
    const timer = setTimeout(done, timeoutMs)
    ipc.on('door:before-close-done', onAnswer)
    target.send('door:before-close')
  })
}

/** A window's close: let it go, or hold it while the page writes first (once). */
export function closeStep(state: { closing: boolean; pagesFlushed: boolean }): 'let-close' | 'flush-first' {
  return state.closing || state.pagesFlushed ? 'let-close' : 'flush-first'
}

/** Before a quit: the pages write first, while the server still answers; only then the update's stop and the server's end. */
export function beforeQuitStep(state: { pagesFlushed: boolean }): 'flush-then-quit' | 'go-on' {
  return state.pagesFlushed ? 'go-on' : 'flush-then-quit'
}
