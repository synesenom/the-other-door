// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ChipInput, FieldLabel } from './parts'

afterEach(cleanup)

describe('ChipInput', () => {
  const show = (props: { placeholder?: string; hint?: string } = {}) => render(<ChipInput label="Search terms" values={[]} onAdd={vi.fn()} onDrop={vi.fn()} {...props} />)

  it('says in the box that Enter adds, and nothing under it', () => {
    show({ placeholder: 'Add a term and press Enter' })
    expect(screen.getByLabelText('Search terms')).toHaveAttribute('placeholder', 'Add a term and press Enter')
    expect(screen.queryByText(/press Enter/i)).toBeNull()
  })
  it('shows the pills under the box, each on one line with its whole text on hover', () => {
    const long = 'head of international financial planning and analysis for the nordics'
    render(<ChipInput label="Search terms" values={[long]} onAdd={vi.fn()} onDrop={vi.fn()} />)
    const box = screen.getByLabelText('Search terms')
    const pills = screen.getByRole('list', { name: 'Search terms, chosen' })
    expect(box.compareDocumentPosition(pills) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByTitle(long)).toHaveClass('chip-text')
  })
  it('can leave its name to the box: no label on screen, still named for a screen reader', () => {
    render(<ChipInput label="Add your own title" hideLabel values={[]} onAdd={vi.fn()} onDrop={vi.fn()} />)
    expect(screen.getByRole('textbox', { name: 'Add your own title' })).toBeInTheDocument()
    expect(screen.queryByText('Add your own title')).toBeNull()
  })
  it('says so with no placeholder of its own too', () => {
    show()
    expect(screen.getByLabelText('Search terms')).toHaveAttribute('placeholder', expect.stringMatching(/press Enter/i))
  })
  it('keeps its explanation behind the icon by its name', async () => {
    show({ hint: 'What the job boards are searched for.' })
    expect(screen.queryByText('What the job boards are searched for.')).toBeNull()
    await userEvent.hover(screen.getByRole('button', { name: 'About Search terms' }))
    expect(screen.getByRole('tooltip')).toHaveTextContent('What the job boards are searched for.')
  })
})

describe('FieldLabel', () => {
  it('has no icon without help, and the icon is not part of the field name', () => {
    render(
      <>
        <FieldLabel htmlFor="a" label="Name" />
        <input id="a" />
        <FieldLabel htmlFor="b" label="City" help="Every board." />
        <input id="b" />
      </>,
    )
    expect(screen.queryByRole('button', { name: 'About Name' })).toBeNull()
    expect(screen.getByRole('button', { name: 'About City' })).toBeInTheDocument()
    expect(screen.getByLabelText('City')).toHaveAttribute('id', 'b')
  })
  it('reaches the words from the keyboard', async () => {
    render(<FieldLabel htmlFor="b" label="City" help="Every board." />)
    await userEvent.tab()
    expect(screen.getByRole('tooltip')).toHaveTextContent('Every board.')
  })
})
