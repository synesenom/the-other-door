import { useEffect, useRef } from 'react'

/**
 * The phone's (and the browser's) Back button, one step at a time: `depth` is how far a screen is from its list
 * (0 the list, 1 a posting, 2 its application), each step one history entry, and Back calls `back` for one step.
 * A step left by the screen's own back link, or by leaving the screen, is taken off the history again, so Back
 * never reopens what was closed and the history holds at most the screen's two steps.
 */
export function useHistoryBack(depth: number, back: () => void) {
  const steps = useRef(0)
  const backNow = useRef(back)
  backNow.current = back

  useEffect(() => {
    if (depth > steps.current) {
      for (let i = steps.current; i < depth; i++) history.pushState({ doorStep: i + 1 }, '')
    } else if (depth < steps.current) {
      history.go(depth - steps.current)
    }
    steps.current = depth
  }, [depth])

  useEffect(() => {
    // Each entry says its step; landing on the step the screen is at already is its own going back, not a press.
    const onPop = (e: PopStateEvent) => {
      const landed = (e.state as { doorStep?: number } | null)?.doorStep ?? 0
      if (landed >= steps.current) return
      steps.current -= 1
      backNow.current()
    }
    window.addEventListener('popstate', onPop)
    return () => {
      window.removeEventListener('popstate', onPop)
      if (steps.current > 0) {
        history.go(-steps.current)
        steps.current = 0
      }
    }
  }, [])
}
