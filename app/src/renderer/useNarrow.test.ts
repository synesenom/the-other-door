// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useNarrow } from './useNarrow'

type Listener = (e: { matches: boolean }) => void

function stubMatchMedia(initial: boolean) {
  const listeners = new Set<Listener>()
  const mql = {
    matches: initial,
    media: '',
    addEventListener: (_: string, l: Listener) => listeners.add(l),
    removeEventListener: (_: string, l: Listener) => listeners.delete(l),
  }
  const mm = vi.fn((q: string) => ((mql.media = q), mql))
  window.matchMedia = mm as unknown as typeof window.matchMedia
  return {
    mm,
    listeners,
    set(v: boolean) {
      mql.matches = v
      listeners.forEach((l) => l({ matches: v }))
    },
  }
}

afterEach(() => {
  delete (window as { matchMedia?: unknown }).matchMedia
})

describe('useNarrow', () => {
  it('asks for widths under the 900 px breakpoint and starts from the current answer', () => {
    const s = stubMatchMedia(true)
    const { result } = renderHook(() => useNarrow())
    expect(s.mm).toHaveBeenCalledWith('(max-width: 899px)')
    expect(result.current).toBe(true)
  })

  it('follows the media query as the window resizes, and stops listening on unmount', () => {
    const s = stubMatchMedia(false)
    const { result, unmount } = renderHook(() => useNarrow())
    expect(result.current).toBe(false)
    act(() => s.set(true))
    expect(result.current).toBe(true)
    act(() => s.set(false))
    expect(result.current).toBe(false)
    unmount()
    expect(s.listeners.size).toBe(0)
  })

  it('is false where there is no matchMedia', () => {
    expect(renderHook(() => useNarrow()).result.current).toBe(false)
  })
})
