// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { Documentation } from './Documentation'

afterEach(cleanup)

describe('Documentation', () => {
  it('lists the documents and opens one in place, without repeating its title', async () => {
    render(<Documentation />)
    expect(screen.getByRole('heading', { name: 'Documentation' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Legal disclaimer' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Legal disclaimer' }))
    expect(dialog.getByRole('heading', { name: 'Your data' })).toBeInTheDocument()
    expect(dialog.getAllByRole('heading', { name: /legal disclaimer/i })).toHaveLength(1)
    await userEvent.click(dialog.getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
