// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Hint } from './Hint'

afterEach(cleanup)

describe('Hint', () => {
  const icon = () => screen.getByRole('button', { name: 'About this' })
  const show = () => render(<Hint label="About this">The words.</Hint>)

  it('opens its words below the icon when above them they would be cut off at the top', async () => {
    // a phone's tap on the icon near the top of the page: the words go where they can be read
    const rect = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      const top = this.getAttribute('role') === 'tooltip' ? -40 : 0
      return { top, bottom: top + 60, left: 0, right: 200, width: 200, height: 60, x: 0, y: top, toJSON: () => ({}) } as DOMRect
    })
    show()
    await userEvent.click(icon())
    expect(screen.getByRole('tooltip')).toHaveClass('below')
    rect.mockRestore()
  })
  it('opens its words above the icon when there is room', async () => {
    show()
    await userEvent.click(icon())
    expect(screen.getByRole('tooltip')).not.toHaveClass('below')
  })
  it('keeps its words out of the way until asked', () => {
    show()
    expect(screen.queryByRole('tooltip')).toBeNull()
  })
  it('opens on hover and closes when the pointer leaves', async () => {
    show()
    await userEvent.hover(icon())
    expect(screen.getByRole('tooltip')).toHaveTextContent('The words.')
    await userEvent.unhover(icon())
    await waitFor(() => expect(screen.queryByRole('tooltip')).toBeNull())
  })
  it('survives the pointer crossing a gap on its way to the words', async () => {
    show()
    await userEvent.hover(icon())
    await userEvent.unhover(icon())
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
    await userEvent.hover(screen.getByRole('tooltip'))
    await new Promise((r) => setTimeout(r, 300))
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
  })
  it('stays open while the pointer is on the words, so they can be read', async () => {
    show()
    await userEvent.hover(icon())
    await userEvent.hover(screen.getByRole('tooltip'))
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
  })
  it('keeps the Escape that closes it to itself, and lets it through when closed', async () => {
    show()
    const heard = vi.fn()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && heard()
    window.addEventListener('keydown', onKey)
    try {
      await userEvent.tab()
      await userEvent.keyboard('{Escape}')
      expect(screen.queryByRole('tooltip')).toBeNull()
      expect(heard).not.toHaveBeenCalled()
      await userEvent.keyboard('{Escape}')
      expect(heard).toHaveBeenCalledTimes(1)
    } finally {
      window.removeEventListener('keydown', onKey)
    }
  })
  it('opens by keyboard, describes the icon, and closes on Escape or leaving', async () => {
    show()
    await userEvent.tab()
    expect(icon()).toHaveFocus()
    expect(icon()).toHaveAccessibleDescription('The words.')
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('tooltip')).toBeNull()
    await userEvent.hover(icon())
    await userEvent.tab()
    await userEvent.unhover(icon())
    await waitFor(() => expect(screen.queryByRole('tooltip')).toBeNull())
  })
})
