// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../testing'
import { CvStyle } from './CvStyle'
import type { FieldSpec } from './profile-form/form'

afterEach(cleanup)

const SPECS: FieldSpec[] = [
  { key: 'cv_accent', type: 'choice', required: false, nullable: false, default: 'blue', choices: ['none', 'navy', 'blue', 'teal', 'forest', 'burgundy', 'plum', 'slate', 'rust'] },
  { key: 'cv_fonts', type: 'choice', required: false, nullable: false, default: 'door', choices: ['door', 'editorial', 'friendly', 'plain'] },
]
const sample = (n: string) => ({ png_base64: `PNG-${n}`, own_cv: true })

function show(handlers: Record<string, unknown> = {}, config: Record<string, unknown> = {}) {
  const h = mockDoor({ cv_style_sample: sample('first'), init_profile: {}, ...handlers })
  render(<CvStyle specs={SPECS} config={config} />)
  return h
}
const colours = () => within(screen.getByRole('group', { name: 'Colour' }))
const fonts = () => within(screen.getByRole('group', { name: 'Fonts' }))

describe('CvStyle', () => {
  it('shows nine colours and four font pairs, the saved ones checked, and a sample of the CV', async () => {
    show({}, { cv_accent: 'navy', cv_fonts: 'plain' })
    expect(colours().getAllByRole('radio')).toHaveLength(9)
    expect(fonts().getAllByRole('radio')).toHaveLength(4)
    expect(colours().getByRole('radio', { name: 'Navy' })).toBeChecked()
    expect(fonts().getByRole('radio', { name: 'Plain' })).toBeChecked()
    const img = await screen.findByRole('img', { name: /sample of your CV/ })
    expect(img).toHaveAttribute('src', 'data:image/png;base64,PNG-first')
  })

  it('opens on blue and the door fonts when nothing is saved, asking for that sample', async () => {
    const { call } = show()
    expect(colours().getByRole('radio', { name: 'Blue' })).toBeChecked()
    expect(fonts().getByRole('radio', { name: 'The other door' })).toBeChecked()
    await waitFor(() => expect(call).toHaveBeenCalledWith('cv_style_sample', { cv_accent: 'blue', cv_fonts: 'door' }))
  })

  it('saves a pick at once with only that key, then asks for the sample again', async () => {
    const user = userEvent.setup()
    const { call } = show({ cv_style_sample: (a: Record<string, unknown>) => sample(String(a['cv_accent'])) })
    await screen.findByRole('img')
    call.mockClear()
    await user.click(colours().getByRole('radio', { name: 'Teal' }))
    await waitFor(() => expect(screen.getByRole('img')).toHaveAttribute('src', 'data:image/png;base64,PNG-teal'))
    expect(call.mock.calls.map((c) => c[0])).toEqual(['init_profile', 'cv_style_sample'])
    expect(call).toHaveBeenCalledWith('init_profile', { other: { cv_accent: 'teal' } })
    expect(call).toHaveBeenCalledWith('cv_style_sample', { cv_accent: 'teal', cv_fonts: 'door' })
  })

  it('a font pick is saved as cv_fonts alone', async () => {
    const user = userEvent.setup()
    const { call } = show()
    await screen.findByRole('img')
    await user.click(fonts().getByRole('radio', { name: 'Editorial' }))
    await waitFor(() => expect(call).toHaveBeenCalledWith('init_profile', { other: { cv_fonts: 'editorial' } }))
  })

  it('ignores a sample that a newer pick replaced', async () => {
    const user = userEvent.setup()
    const waiting: Record<string, (v: unknown) => void> = {}
    const { call } = show({ cv_style_sample: (a: Record<string, unknown>) => (a['cv_accent'] === 'blue' ? sample('blue') : new Promise((resolve) => (waiting[String(a['cv_accent'])] = resolve))) })
    await screen.findByRole('img')
    await user.click(colours().getByRole('radio', { name: 'Teal' }))
    await waitFor(() => expect(waiting['teal']).toBeDefined())
    await user.click(colours().getByRole('radio', { name: 'Rust' }))
    await waitFor(() => expect(waiting['rust']).toBeDefined())
    waiting['rust']!(sample('rust'))
    await waitFor(() => expect(screen.getByRole('img')).toHaveAttribute('src', 'data:image/png;base64,PNG-rust'))
    waiting['teal']!(sample('teal'))
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.getByRole('img')).toHaveAttribute('src', 'data:image/png;base64,PNG-rust')
    expect(call).toHaveBeenCalledWith('cv_style_sample', { cv_accent: 'teal', cv_fonts: 'door' })
  })

  it('moves within a group with the arrow keys, which picks', async () => {
    const user = userEvent.setup()
    const { call } = show()
    await screen.findByRole('img')
    colours().getByRole('radio', { name: 'Blue' }).focus()
    await user.keyboard('{ArrowRight}')
    expect(colours().getByRole('radio', { name: 'Teal' })).toBeChecked()
    await waitFor(() => expect(call).toHaveBeenCalledWith('init_profile', { other: { cv_accent: 'teal' } }))
  })

  it('says a CV that could not be read in one line under the sample, which keeps its placeholder', async () => {
    show({ cv_style_sample: () => { throw { message: 'cv_unreadable' } } })
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/Check your Master CV/)
    expect(alert).toHaveClass('field-error')
    expect(screen.queryByRole('img')).toBeNull()
    expect(alert.closest('.style-sample')).toBeNull()
  })

  it('says nothing of a print that failed: the last picture stays', async () => {
    const user = userEvent.setup()
    show({ cv_style_sample: (a: Record<string, unknown>) => { if (a['cv_accent'] === 'blue') return sample('first'); throw { message: 'print_failed' } } })
    await screen.findByRole('img')
    await user.click(colours().getByRole('radio', { name: 'Teal' }))
    await waitFor(() => expect(colours().getByRole('radio', { name: 'Teal' })).toBeChecked())
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByRole('img')).toHaveAttribute('src', 'data:image/png;base64,PNG-first')
  })

  it('prints the sample again once the CV has been saved', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const h = mockDoor({ cv_style_sample: sample('first'), init_profile: {} })
      const { rerender } = render(<CvStyle specs={SPECS} config={{}} cvSaves={0} />)
      await screen.findByRole('img')
      h.call.mockClear()
      rerender(<CvStyle specs={SPECS} config={{}} cvSaves={1} />)
      rerender(<CvStyle specs={SPECS} config={{}} cvSaves={2} />)
      await vi.advanceTimersByTimeAsync(2500)
      expect(h.call.mock.calls.filter((c) => c[0] === 'cv_style_sample')).toHaveLength(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('puts a pick back and says why when it could not be saved', async () => {
    const user = userEvent.setup()
    show({ init_profile: () => { throw { message: 'profile/config.json: cv_accent — bad' } } })
    await screen.findByRole('img')
    await user.click(colours().getByRole('radio', { name: 'Teal' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('cv_accent')
    expect(colours().getByRole('radio', { name: 'Blue' })).toBeChecked()
  })

  it('gives each tile a tooltip', async () => {
    show()
    expect(colours().getByRole('radio', { name: 'Burgundy' }).closest('label')).toHaveAttribute('title', 'Burgundy')
  })
})
