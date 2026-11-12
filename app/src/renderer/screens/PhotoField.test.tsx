// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PhotoField, photoHelp } from './PhotoField'

afterEach(cleanup)

const props = { onChoose: vi.fn(), onRemove: vi.fn() }

describe('PhotoField', () => {
  it('offers to choose a photo when there is none, and nothing to remove', async () => {
    const onChoose = vi.fn()
    render(<PhotoField {...props} onChoose={onChoose} help="x" />)
    expect(screen.queryByRole('img')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Choose a photo…' }))
    expect(onChoose).toHaveBeenCalled()
  })

  it('shows the photo it has, and offers to change or remove it', async () => {
    const onRemove = vi.fn()
    render(<PhotoField {...props} onRemove={onRemove} src="door-file://profile/photo.jpg?v=2" />)
    expect(screen.getByRole('img', { name: 'Your photo' })).toHaveAttribute('src', 'door-file://profile/photo.jpg?v=2')
    expect(screen.getByRole('button', { name: 'Change photo…' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
    expect(onRemove).toHaveBeenCalled()
  })

  it('names a picture chosen but not saved yet, which has no preview', () => {
    render(<PhotoField {...props} pending="portrait.jpg" />)
    expect(screen.getByText('portrait.jpg')).toBeInTheDocument()
    expect(screen.queryByRole('img')).toBeNull()
    expect(screen.getByRole('button', { name: 'Remove' })).toBeInTheDocument()
  })

  it('says why a picture was refused, under the field', () => {
    render(<PhotoField {...props} error="the picture is too small (50 x 50 px)" />)
    expect(screen.getByRole('alert')).toHaveTextContent('the picture is too small')
  })

  it('cannot be used while it works', () => {
    render(<PhotoField {...props} busy />)
    expect(screen.getByRole('button', { name: 'Choose a photo…' })).toBeDisabled()
  })
})

describe('photoHelp', () => {
  it('says what the country does with a photo', () => {
    expect(photoHelp('optional')).toMatch(/optional/i)
    expect(photoHelp('expected')).toMatch(/usually/i)
    expect(photoHelp('no')).toMatch(/not/i)
  })
})
