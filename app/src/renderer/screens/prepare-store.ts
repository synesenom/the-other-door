// Prepares in flight, by job: a Prepare outlives the pane that started it (a remount finds it here), and
// while one runs the server refuses a run, so Find new jobs is off (usePreparing).
import { useSyncExternalStore } from 'react'

export const preparing = new Map<string, { since: number; message: string }>()
const listeners = new Set<() => void>()

/** Says a Prepare started or ended, to everyone who shows whether one runs. */
export function preparingChanged(): void {
  for (const l of listeners) l()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Whether a Prepare is running in this window. */
export function usePreparing(): boolean {
  return useSyncExternalStore(subscribe, () => preparing.size > 0)
}
