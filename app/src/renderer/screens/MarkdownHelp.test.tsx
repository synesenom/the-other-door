// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { mockDoor } from '../testing'
import { MARKDOWN_CHEATSHEET, MarkdownLink } from './MarkdownHelp'

afterEach(cleanup)

describe('MarkdownLink', () => {
  it('opens the cheatsheet in the browser', async () => {
    const { openExternal } = mockDoor({})
    render(<MarkdownLink />)
    await userEvent.click(screen.getByRole('button', { name: 'Markdown' }))
    expect(openExternal).toHaveBeenCalledWith(MARKDOWN_CHEATSHEET)
  })
})
