// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { PageSections } from './PageSections'

afterEach(cleanup)

describe('PageSections', () => {
  it('a jump marks the part and unfolds the closed fold it is in', async () => {
    render(
      <div className="main">
        <PageSections sections={[{ id: 'a', label: 'Details' }, { id: 'b', label: 'Maintenance' }]} />
        <h2 id="a">Details</h2>
        <details>
          <summary>More</summary>
          <h2 id="b">Maintenance</h2>
        </details>
      </div>,
    )
    await userEvent.click(screen.getByRole('link', { name: 'Details' }))
    expect(screen.getByRole('link', { name: 'Details' })).toHaveAttribute('aria-current', 'location')
    expect(document.querySelector('details')).not.toHaveAttribute('open')
    await userEvent.click(screen.getByRole('link', { name: 'Maintenance' }))
    expect(screen.getByRole('link', { name: 'Maintenance' })).toHaveAttribute('aria-current', 'location')
    expect(document.querySelector('details')).toHaveAttribute('open')
  })
})
