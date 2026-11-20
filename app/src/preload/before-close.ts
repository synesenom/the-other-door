/** The page's answer to "the window is closing": every registered writer runs, and the answer is sent once all
 * have settled (a rejection too), at once when none is registered. */
export function beforeCloseHandler(writers: Iterable<() => Promise<void>>, answer: () => void): () => void {
  return () => {
    void Promise.allSettled([...writers].map((w) => Promise.resolve().then(w))).then(answer)
  }
}
