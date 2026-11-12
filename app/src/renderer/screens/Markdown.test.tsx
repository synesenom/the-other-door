// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { mockDoor } from '../testing'
import { Markdown } from './Markdown'

afterEach(cleanup)

describe('Markdown', () => {
  it('headings one level below the page, paragraphs and lists', () => {
    const { container } = render(<Markdown text={'# Report\n\nSome **bold** and *soft* text\nthat wraps.\n\n## Plan\n\n- one\n- two `code`\n\n1. first\n2. second\n'} />)
    expect(screen.getByRole('heading', { name: 'Report', level: 2 })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Plan', level: 3 })).toBeInTheDocument()
    expect(container.querySelector('p')!.textContent).toBe('Some bold and soft text that wraps.')
    expect(container.querySelector('strong')!.textContent).toBe('bold')
    expect(container.querySelector('em')!.textContent).toBe('soft')
    expect(container.querySelector('ul')!.textContent).toBe('onetwo code')
    expect(container.querySelector('ol')!.querySelectorAll('li')).toHaveLength(2)
    expect(container.querySelector('code')!.textContent).toBe('code')
  })

  describe('with onGap', () => {
    const marks = () => screen.getAllByRole('button', { name: 'to fill in' })

    it('leaves TODO as text without it', () => {
      const { container } = render(<Markdown text="Phone: TODO" />)
      expect(container.textContent).toBe('Phone: TODO')
      expect(screen.queryByRole('button')).toBeNull()
    })

    it('marks a TODO anywhere in a line, in the order of the text', async () => {
      const gaps: number[] = []
      const { container } = render(<Markdown text={'# TODO\n\nMSc, TODO year, **TODO**\n\n- *TODO*\n- `TODO`\n'} onGap={(n) => gaps.push(n)} />)
      expect(marks()).toHaveLength(5)
      expect(container.querySelector('p')!.textContent).toBe('MSc, to fill in year, to fill in')
      for (const mark of marks()) await userEvent.click(mark)
      expect(gaps).toEqual([0, 1, 2, 3, 4])
    })

    it('does not mark a word that only contains it', () => {
      render(<Markdown text="MASTODON and TODOS" onGap={() => undefined} />)
      expect(screen.queryByRole('button')).toBeNull()
    })

    it('a TODO in a link is not marked, and the next marker still means the right gap', async () => {
      const gaps: number[] = []
      render(<Markdown text="[TODO](https://example.com/TODO) then TODO" onGap={(n) => gaps.push(n)} />)
      await userEvent.click(screen.getByRole('button', { name: 'to fill in' }))
      expect(gaps).toEqual([2])
    })
  })

  it('never renders markup from the text', () => {
    const { container } = render(<Markdown text={'<img src=x onerror=alert(1)> <script>alert(1)</script>\n\n<b>hi</b>'} />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('b')).toBeNull()
    expect(container.textContent).toContain('<img src=x onerror=alert(1)>')
  })

  it('a web link opens in the browser through the main process; anything else is plain text', async () => {
    const { openExternal } = mockDoor({})
    render(<Markdown text={'See [the course](https://example.com/sql) and [this](javascript:alert(1)) and [file](file:///etc/passwd).'} />)
    await userEvent.click(screen.getByRole('button', { name: 'the course' }))
    expect(openExternal).toHaveBeenCalledWith('https://example.com/sql')
    expect(screen.queryByRole('button', { name: 'this' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'file' })).toBeNull()
    expect(screen.getByText(/javascript:alert/)).toBeInTheDocument()
  })
})
