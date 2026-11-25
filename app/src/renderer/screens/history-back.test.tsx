// @vitest-environment jsdom
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useHistoryBack } from './history-back'

function Screen({ depth, back }: { depth: number; back: () => void }) {
  useHistoryBack(depth, back)
  return null
}

// jsdom runs history.go's popstate after a task, as a browser does
const settle = () => act(() => new Promise((r) => setTimeout(r, 20)))

describe('the phone back button', () => {
  afterEach(cleanup)

  it('goes back one step from the posting to the list, and adds no step on the list', async () => {
    const start = history.length
    const back = vi.fn()
    const { rerender } = render(<Screen depth={0} back={back} />)
    expect(history.length).toBe(start)
    rerender(<Screen depth={1} back={back} />)
    expect(history.length).toBe(start + 1)
    history.back()
    await settle()
    expect(back).toHaveBeenCalledTimes(1)
  })

  it('a step left by the screen\'s own back link is taken off the history, and calls nothing', async () => {
    const back = vi.fn()
    const { rerender } = render(<Screen depth={0} back={back} />)
    rerender(<Screen depth={1} back={back} />)
    rerender(<Screen depth={2} back={back} />)
    rerender(<Screen depth={0} back={back} />)
    await settle()
    expect(back).not.toHaveBeenCalled()
    history.back() // leaves the app's page, never reopens a posting
    await settle()
    expect(back).not.toHaveBeenCalled()
  })

  it('goes back from the application to the posting, then to the list', async () => {
    let depth = 2
    const back = vi.fn(() => (depth -= 1))
    const { rerender } = render(<Screen depth={0} back={back} />)
    rerender(<Screen depth={1} back={back} />)
    rerender(<Screen depth={2} back={back} />)
    history.back()
    await settle()
    rerender(<Screen depth={depth} back={back} />)
    expect(depth).toBe(1)
    history.back()
    await settle()
    rerender(<Screen depth={depth} back={back} />)
    expect(depth).toBe(0)
  })
})
