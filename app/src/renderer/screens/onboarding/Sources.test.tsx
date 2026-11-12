// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../../testing'
import { Sources } from './Sources'
import { existingProfile, Host } from './testing'

afterEach(cleanup)

function setup({ profile = undefined as typeof existingProfile | undefined, handlers = {} } = {}) {
  const h = mockDoor(handlers)
  const onNext = vi.fn()
  render(<Host profile={profile}>{(state, dispatch) => <Sources state={state} dispatch={dispatch} onNext={onNext} />}</Host>)
  return { ...h, onNext }
}
const file = (name: string) => ({ token: `t-${name}`, name, size: 10 })

describe('Sources', () => {
  it('Continue waits for a source, then goes on', async () => {
    const { pickCvFiles, onNext } = setup()
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
    pickCvFiles.mockResolvedValue({ files: [file('cv.pdf')], refused: [] })
    await userEvent.click(screen.getByRole('button', { name: 'Drop relevant documents here (CV or LinkedIn PDF)' }))
    expect(await screen.findByText('cv.pdf')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(onNext).toHaveBeenCalled()
  })

  it('lists files and pages together, and removes either', async () => {
    const { pickCvFiles } = setup()
    pickCvFiles.mockResolvedValue({ files: [file('cv.pdf')], refused: [] })
    await userEvent.click(screen.getByRole('button', { name: 'Drop relevant documents here (CV or LinkedIn PDF)' }))
    await screen.findByText('cv.pdf')
    await userEvent.type(screen.getByLabelText('Any relevant URL'), 'https://ada.dev{Enter}')
    const list = screen.getByRole('list', { name: 'Sources, chosen' })
    expect(list).toHaveTextContent('cv.pdf')
    expect(list).toHaveTextContent('https://ada.dev')
    await userEvent.click(screen.getByRole('button', { name: 'Remove https://ada.dev' }))
    expect(list).not.toHaveTextContent('https://ada.dev')
  })

  it('takes dropped files through the preload, which alone knows their paths', async () => {
    const { dropCvFiles } = setup()
    dropCvFiles.mockResolvedValue({ files: [file('linkedin.pdf')], refused: [{ name: 'x.png', reason: 'Only PDF' }] })
    const dropped = new File(['x'], 'linkedin.pdf')
    fireEvent.drop(screen.getByRole('button', { name: 'Drop relevant documents here (CV or LinkedIn PDF)' }), { dataTransfer: { files: [dropped] } })
    expect(await screen.findByText('linkedin.pdf')).toBeInTheDocument()
    expect(dropCvFiles).toHaveBeenCalledWith([dropped])
    expect(screen.getByRole('alert')).toHaveTextContent('x.png: Only PDF')
  })

  it('removes a file', async () => {
    const { pickCvFiles } = setup()
    pickCvFiles.mockResolvedValue({ files: [file('cv.pdf')], refused: [] })
    await userEvent.click(screen.getByRole('button', { name: 'Drop relevant documents here (CV or LinkedIn PDF)' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Remove cv.pdf' }))
    expect(screen.queryByText('cv.pdf')).toBeNull()
  })

  it('takes a page; refuses LinkedIn and what is no address', async () => {
    setup()
    const field = screen.getByLabelText('Any relevant URL')
    await userEvent.type(field, 'https://www.linkedin.com/in/ada{Enter}')
    expect(screen.getByRole('alert')).toHaveTextContent('Save to PDF')
    await userEvent.clear(field)
    await userEvent.type(field, 'nope{Enter}')
    expect(screen.getByRole('alert')).toHaveTextContent('not a web page')
    await userEvent.clear(field)
    await userEvent.type(field, 'https://ada.dev{Enter}')
    expect(screen.getByText('https://ada.dev')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled()
  })

  it('takes a typed page on leaving the field too, so Enter is not a thing to know', async () => {
    setup()
    await userEvent.type(screen.getByPlaceholderText('Any relevant URL, then press Enter'), 'https://ada.dev')
    await userEvent.tab()
    expect(screen.getByText('https://ada.dev')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled()
  })

  it('an address typed as the only source lets Continue go, and is read', async () => {
    const { onNext } = setup()
    fireEvent.change(screen.getByLabelText('Any relevant URL'), { target: { value: 'https://ada.dev' } })
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Continue' })) // no blur first: the click itself takes it
    expect(onNext).toHaveBeenCalled()
    expect(screen.getByRole('list', { name: 'Sources, chosen' })).toHaveTextContent('https://ada.dev')
  })

  it('leaving the box for Continue leaves the address to Continue, so the buttons do not move under the click', async () => {
    const { onNext } = setup()
    const box = screen.getByLabelText('Any relevant URL')
    fireEvent.change(box, { target: { value: 'https://ada.dev' } })
    fireEvent.blur(box, { relatedTarget: screen.getByRole('button', { name: 'Continue' }) })
    expect(screen.queryByRole('list', { name: 'Sources, chosen' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(onNext).toHaveBeenCalled()
    expect(screen.getByRole('list', { name: 'Sources, chosen' })).toHaveTextContent('https://ada.dev')
  })

  it('an address typed that cannot be read does not let Continue go', async () => {
    setup()
    fireEvent.change(screen.getByLabelText('Any relevant URL'), { target: { value: 'ada.dev' } })
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
  })

  it('refuses a LinkedIn address written with a trailing dot', async () => {
    setup()
    await userEvent.type(screen.getByLabelText('Any relevant URL'), 'https://linkedin.com./in/ada{Enter}')
    expect(screen.getByRole('alert')).toHaveTextContent('Save to PDF')
    expect(screen.queryByRole('list', { name: 'Sources, chosen' })).toBeNull()
  })

  it('says what files and pages it takes only when asked', async () => {
    setup()
    expect(screen.queryByRole('tooltip')).toBeNull()
    await userEvent.hover(screen.getByRole('button', { name: 'About the documents' }))
    expect(screen.getByRole('tooltip')).toHaveTextContent('PDF, DOCX, Markdown or text, up to 25 MB each. On LinkedIn: More → Save to PDF.')
    await userEvent.unhover(screen.getByRole('button', { name: 'About the documents' }))
    await waitFor(() => expect(screen.queryByRole('tooltip')).toBeNull())
    await userEvent.hover(screen.getByRole('button', { name: 'About the URL' }))
    expect(screen.getByRole('tooltip')).toHaveTextContent('A personal site, GitHub, a publication list: anything public.')
  })

  it('a file dropped on the hint icon still counts as dropped', async () => {
    const { dropCvFiles } = setup()
    dropCvFiles.mockResolvedValue({ files: [file('cv.pdf')], refused: [] })
    fireEvent.drop(screen.getByRole('button', { name: 'About the documents' }), { dataTransfer: { files: [new File(['x'], 'cv.pdf')] } })
    expect(await screen.findByText('cv.pdf')).toBeInTheDocument()
  })
})
