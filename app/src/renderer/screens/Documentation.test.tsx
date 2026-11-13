// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { DocDialog, Documentation } from './Documentation'

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

  it('drops the title of a document written with Windows line endings too', () => {
    // a Windows checkout builds the app from CRLF files (#18): the title was shown twice
    render(<DocDialog doc={{ title: 'Notes', text: '# Notes\r\n\r\nThe body.\r\n' }} onClose={() => {}} />)
    const dialog = within(screen.getByRole('dialog', { name: 'Notes' }))
    expect(dialog.getAllByRole('heading', { name: 'Notes' })).toHaveLength(1)
    expect(dialog.getByText('The body.')).toBeInTheDocument()
  })
})
