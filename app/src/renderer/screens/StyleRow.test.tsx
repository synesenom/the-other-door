// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../testing'
import { StyleRow } from './StyleRow'

afterEach(cleanup)

const set = (version: string, extra: Record<string, unknown> = {}) => ({
  cv: [`/h/.style/preview/x/cv_page_1.png`, `/h/.style/preview/x/cv_page_2.png`],
  letter: [`/h/.style/preview/x/letter_page_1.png`],
  version,
  two_column: false,
  ...extra,
})
const shown = (over: Record<string, unknown> = {}) => ({ styles: { default: set('d1') }, in_use: 'default', candidate: false, ...over })
const both = (over: Record<string, unknown> = {}) => shown({ styles: { default: set('d1'), like: set('l1') }, ...over })

async function open(handlers: Record<string, unknown>, props: Partial<Parameters<typeof StyleRow>[0]> = {}) {
  const h = mockDoor({ show_style: shown(), ...handlers })
  const onChanged = vi.fn()
  const view = render(<StyleRow state="none" canBuild onChanged={onChanged} reload={0} {...props} />)
  return { ...h, onChanged, view }
}
const ready = () => screen.findByRole('img', { name: /The other door's/ })

describe('StyleRow, the first read', () => {
  it('holds the place with empty sheets and one quiet line, and offers nothing, while the previews are made', async () => {
    mockDoor({ show_style: () => new Promise(() => undefined) })
    render(<StyleRow state="none" canBuild onChanged={() => undefined} reload={0} />)
    expect(await screen.findByText('Preparing the previews…')).toBeTruthy()
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('says nothing, and keeps only the build action, when nothing could be printed', async () => {
    await open({ show_style: { styles: {}, in_use: 'default', candidate: false } })
    expect(await screen.findByRole('button', { name: 'Use the style of my CV…' })).toBeTruthy()
    expect(screen.queryByRole('img')).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('says nothing when the previews fail', async () => {
    mockDoor({ show_style: () => { throw new Error('boom') } })
    render(<StyleRow state="none" canBuild onChanged={() => undefined} reload={0} />)
    expect(await screen.findByRole('button', { name: 'Use the style of my CV…' })).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

describe('StyleRow, no style of your own yet', () => {
  it("shows The other door's in use, what a style is for, and the way to make one", async () => {
    await open({})
    const img = await ready()
    expect(img.getAttribute('src')).toBe('door-file://style/default/cv_page_1.png?v=d1')
    expect(screen.getByText('In use')).toBeTruthy()
    expect(screen.getByText(/Make your tailored CVs look like a CV of yours\. Takes 2–5 minutes in the background\./)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Use the style of my CV…' }).className).toBe('secondary')
  })

  it('starts a build from the file chosen in main, and tells the app', async () => {
    const h = await open({})
    await ready()
    await userEvent.click(screen.getByRole('button', { name: 'Use the style of my CV…' }))
    await waitFor(() => expect(h.onChanged).toHaveBeenCalled())
    expect(h.chooseStyleFile).toHaveBeenCalled()
  })

  it('does nothing when the dialog is cancelled, and names a refusal the user can act on', async () => {
    const h = await open({})
    await ready()
    h.chooseStyleFile.mockResolvedValueOnce({ ok: true, data: { canceled: true } })
    await userEvent.click(screen.getByRole('button', { name: 'Use the style of my CV…' }))
    await waitFor(() => expect(h.chooseStyleFile).toHaveBeenCalled())
    expect(h.onChanged).not.toHaveBeenCalled()
    h.chooseStyleFile.mockResolvedValueOnce({ ok: false, error: 'this PDF is a scan: there is no style to copy' })
    await userEvent.click(screen.getByRole('button', { name: 'Use the style of my CV…' }))
    expect((await screen.findByRole('alert')).textContent).toContain('this PDF is a scan')
  })

  it('has no way to build on made-up data', async () => {
    await open({}, { canBuild: false })
    await ready()
    expect(screen.queryByRole('button', { name: /Use the style of/ })).toBeNull()
  })

  it('while a build runs, the sheet stays and a quiet line replaces the button', async () => {
    await open({}, { state: 'building' })
    await ready()
    expect(screen.getByText('Building your style…')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Use the style of/ })).toBeNull()
  })

  it('goes back to this, saying nothing, when the build failed', async () => {
    await open({}, { state: 'failed' })
    await ready()
    expect(screen.getByRole('button', { name: 'Use the style of my CV…' })).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

describe('StyleRow, a style built and waiting', () => {
  const waiting = { show_style: both({ candidate: true }) }

  it('compares the two, the choice under the new one a secondary button (Save is the one primary)', async () => {
    await open(waiting, { state: 'ready' })
    await ready()
    expect(screen.getByRole('img', { name: /Like your CV/ }).getAttribute('src')).toBe('door-file://style/like/cv_page_1.png?v=l1')
    expect(screen.getByRole('button', { name: 'Use this style' }).className).toBe('secondary')
    expect(screen.getAllByRole('button').filter((b) => b.className === 'primary')).toHaveLength(0)
    expect(screen.queryByText('Use the style of another CV…')).toBeNull()
  })

  it('uses it: use_style like, the app told, then the question about the prepared CVs', async () => {
    const calls: Record<string, unknown>[] = []
    const h = await open({ ...waiting, use_style: (a: Record<string, unknown>) => (calls.push(a), { in_use: 'like', prepared: 2 }) }, { state: 'ready' })
    await ready()
    await userEvent.click(screen.getByRole('button', { name: 'Use this style' }))
    expect(await screen.findByRole('button', { name: 'Print 2 prepared CVs again' })).toBeTruthy()
    expect(calls[0]).toEqual({ style: 'like' })
    expect(h.onChanged).toHaveBeenCalled()
  })

  it("keeps The other door's: use_style default", async () => {
    const calls: Record<string, unknown>[] = []
    await open({ ...waiting, use_style: (a: Record<string, unknown>) => (calls.push(a), { in_use: 'default', prepared: 0 }) }, { state: 'ready' })
    await ready()
    await userEvent.click(screen.getByRole('button', { name: "Keep The other door's" }))
    await waitFor(() => expect(calls).toEqual([{ style: 'default' }]))
  })

  it('with an earlier style in use says so, and can keep it: use_style current', async () => {
    const calls: Record<string, unknown>[] = []
    await open({ show_style: both({ candidate: true, in_use: 'like' }), use_style: (a: Record<string, unknown>) => (calls.push(a), { in_use: 'like', prepared: 3 }) }, { state: 'ready' })
    await ready()
    expect(screen.getByText('Your earlier style is in use.')).toBeTruthy()
    expect(screen.queryByText('In use')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Keep my current style' }))
    await waitFor(() => expect(calls).toEqual([{ style: 'current' }]))
    expect(screen.queryByRole('button', { name: /Print .* again/ })).toBeNull() // nothing changed in use
  })

  it('reads the previews again when the build is ready', async () => {
    const h = mockDoor({ show_style: shown() })
    const { rerender } = render(<StyleRow state="building" canBuild onChanged={() => undefined} reload={0} />)
    await screen.findByRole('img', { name: /The other door's/ })
    h.call.mockClear()
    rerender(<StyleRow state="ready" canBuild onChanged={() => undefined} reload={0} />)
    await waitFor(() => expect(h.call).toHaveBeenCalledWith('show_style', {}))
  })
})

describe('StyleRow, a style of your own in use or kept', () => {
  it("sets The other door's first, then yours, and Keep before Use under yours", async () => {
    await open({ show_style: both({ candidate: true, in_use: 'like' }) })
    await ready()
    expect(screen.getAllByRole('group').filter((g) => g.className === 'style-card').map((g) => g.textContent?.slice(0, 9))).toEqual(["The other", 'Like your'])
    const like = within(screen.getByRole('group', { name: 'Like your CV' }))
    expect(like.getAllByRole('button').map((b) => b.textContent).slice(1)).toEqual(['Keep my current style', 'Use this style'])
  })

  it('marks the one in use, and offers the other', async () => {
    await open({ show_style: both({ in_use: 'like' }) })
    await ready()
    const like = screen.getByRole('group', { name: 'Like your CV' })
    expect(within(like).getByText('In use')).toBeTruthy()
    expect(within(screen.getByRole('group', { name: "The other door's" })).queryByText('In use')).toBeNull()
    expect(screen.getByRole('button', { name: "Use The other door's" })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Use the style of another CV…' })).toBeTruthy()
  })

  it("with The other door's in use and a style kept, offers to go back to it", async () => {
    const calls: Record<string, unknown>[] = []
    await open({ show_style: both(), use_style: (a: Record<string, unknown>) => (calls.push(a), { in_use: 'like', prepared: 0 }) })
    await ready()
    expect(within(screen.getByRole('group', { name: "The other door's" })).getByText('In use')).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: "Use my CV's style" }))
    await waitFor(() => expect(calls).toEqual([{ style: 'like' }]))
    expect(screen.queryByRole('button', { name: /Print .* again/ })).toBeNull() // no prepared CV
  })

  it('says a two-column style may read less well to application systems', async () => {
    await open({ show_style: both({ styles: { default: set('d1'), like: set('l1', { two_column: true }) } }) })
    await ready()
    expect(screen.getByText('Some application systems read two-column CVs less well.')).toBeTruthy()
  })
})

describe('StyleRow, the prepared CVs after a switch', () => {
  const switched = (prepared: number, result: Record<string, unknown>) => ({
    show_style: both({ candidate: true }),
    use_style: (a: Record<string, unknown>) => (a['rerender'] ? { in_use: 'like', prepared, ...result } : { in_use: 'like', prepared }),
  })
  const use = async (prepared: number, result: Record<string, unknown>) => {
    const h = await open(switched(prepared, result), { state: 'ready' })
    await ready()
    await userEvent.click(screen.getByRole('button', { name: 'Use this style' }))
    return h
  }

  it('says "1 prepared CV" for one', async () => {
    await use(1, {})
    expect(await screen.findByRole('button', { name: 'Print 1 prepared CV again' })).toBeTruthy()
  })

  it('re-renders on request with the style now in use, then says how many', async () => {
    const h = await use(2, { rerendered: ['a.1', 'a.2'], failed: [] })
    await userEvent.click(await screen.findByRole('button', { name: 'Print 2 prepared CVs again' }))
    expect(await screen.findByText('2 printed again.')).toBeTruthy()
    expect(h.call).toHaveBeenCalledWith('use_style', { style: 'like', rerender: true })
    expect(screen.queryByRole('button', { name: /Print .* again/ })).toBeNull()
  })

  it('says it is busy while it prints', async () => {
    let finish: (v: unknown) => void = () => undefined
    mockDoor({
      show_style: both({ candidate: true }),
      use_style: (a: Record<string, unknown>) => (a['rerender'] ? new Promise((r) => (finish = r)) : { in_use: 'like', prepared: 2 }),
    })
    render(<StyleRow state="ready" canBuild onChanged={() => undefined} reload={0} />)
    await ready()
    await userEvent.click(screen.getByRole('button', { name: 'Use this style' }))
    await userEvent.click(await screen.findByRole('button', { name: /Print 2 prepared/ }))
    expect(await screen.findByText('Printing again…')).toBeTruthy()
    finish({ in_use: 'like', prepared: 2, rerendered: ['a.1', 'a.2'], failed: [] })
    expect(await screen.findByText('2 printed again.')).toBeTruthy()
  })

  it('names how many could not be printed', async () => {
    await use(3, { rerendered: ['a.1', 'a.2'], failed: ['a.3'] })
    await userEvent.click(await screen.findByRole('button', { name: /Print 3 prepared/ }))
    expect(await screen.findByText('2 printed again.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })
})

describe('StyleRow, after a print that failed for some', () => {
  it('offers Try again, which prints again and, when all go through, offers nothing more', async () => {
    let round = 0
    mockDoor({
      show_style: both({ candidate: true }),
      use_style: (a: Record<string, unknown>) =>
        a['rerender'] ? (round++ === 0 ? { in_use: 'like', prepared: 3, rerendered: ['a.1', 'a.2'], failed: ['a.3'] } : { in_use: 'like', prepared: 3, rerendered: ['a.1', 'a.2', 'a.3'], failed: [] }) : { in_use: 'like', prepared: 3 },
    })
    render(<StyleRow state="ready" canBuild onChanged={() => undefined} reload={0} />)
    await ready()
    await userEvent.click(screen.getByRole('button', { name: 'Use this style' }))
    await userEvent.click(await screen.findByRole('button', { name: /Print 3 prepared/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('3 printed again.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
  })
})

describe('StyleRow, the full pages', () => {
  it('opens a style in a dialog to read, CV and letter, and closes with Escape', async () => {
    await open({ show_style: both() })
    await ready()
    await userEvent.click(screen.getByRole('button', { name: 'Show Like your CV in full' }))
    const dialog = await screen.findByRole('dialog', { name: 'Like your CV' })
    expect(within(dialog).getByRole('button', { name: 'CV · 2 pages' }).getAttribute('aria-pressed')).toBe('true')
    expect(within(dialog).getAllByRole('img').map((i) => i.getAttribute('src'))).toEqual(['door-file://style/like/cv_page_1.png?v=l1', 'door-file://style/like/cv_page_2.png?v=l1'])
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cover letter · 1 page' }))
    expect(within(dialog).getAllByRole('img').map((i) => i.getAttribute('src'))).toEqual(['door-file://style/like/letter_page_1.png?v=l1'])
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('StyleRow, reading again', () => {
  it('keeps the sheets on screen while the previews are made again after a save', async () => {
    mockDoor({ show_style: shown() })
    const { rerender } = render(<StyleRow state="none" canBuild onChanged={() => undefined} reload={0} />)
    await ready()
    mockDoor({ show_style: () => new Promise(() => undefined) })
    rerender(<StyleRow state="none" canBuild onChanged={() => undefined} reload={1} />)
    expect(screen.getByRole('img', { name: /The other door's/ })).toBeTruthy()
    expect(screen.queryByText('Preparing the previews…')).toBeNull()
  })
})
