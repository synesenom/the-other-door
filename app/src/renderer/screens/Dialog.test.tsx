// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Dialog } from './Dialog'

afterEach(cleanup)

describe('Dialog', () => {
  it('is a modal dialog named by its title, with its children', () => {
    render(
      <Dialog title="Hello there" onClose={() => {}}>
        <button type="button">Inside</button>
      </Dialog>,
    )
    const d = screen.getByRole('dialog', { name: 'Hello there' })
    expect(d).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByRole('button', { name: 'Inside' })).toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    const onClose = vi.fn()
    render(
      <Dialog title="T" onClose={onClose}>
        <button type="button">A</button>
      </Dialog>,
    )
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })

  it('wraps Tab and Shift-Tab around its controls', async () => {
    render(
      <Dialog title="T" onClose={() => {}}>
        <button type="button">A</button>
        <button type="button">B</button>
      </Dialog>,
    )
    const a = screen.getByRole('button', { name: 'A' })
    const b = screen.getByRole('button', { name: 'B' })
    a.focus()
    await userEvent.tab({ shift: true })
    expect(b).toHaveFocus()
    await userEvent.tab()
    expect(a).toHaveFocus()
  })

  it('puts focus on the element it is told to, else on the first control', () => {
    render(
      <Dialog title="T" onClose={() => {}}>
        <button type="button">A</button>
      </Dialog>,
    )
    expect(screen.getByRole('button', { name: 'A' })).toHaveFocus()
  })

  it('opens at its top even when the first control is at the bottom of a long text', () => {
    // the legal disclaimer's only control is Close, under the whole text: focusing it scrolled the dialog to the end
    const focus = vi.spyOn(HTMLElement.prototype, 'focus')
    render(
      <Dialog title="T" onClose={() => {}}>
        <p>a long text</p>
        <button type="button">Close</button>
      </Dialog>,
    )
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
    expect(focus).toHaveBeenCalledWith({ preventScroll: true })
    focus.mockRestore()
  })
})
