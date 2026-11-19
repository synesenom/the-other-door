// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
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
const ready = () => screen.findByRole('img', { name: /The other door/ })

describe('StyleRow, the first read', () => {
  it('holds the place with an empty sheet and one quiet line, and offers nothing, while the previews are made', async () => {
    mockDoor({ show_style: () => new Promise(() => undefined) })
    render(<StyleRow state="none" canBuild onChanged={() => undefined} reload={0} />)
    expect(await screen.findByText('Preparing the previews…')).toBeTruthy()
    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.queryByRole('switch')).toBeNull()
  })

  it('says nothing, and keeps only the switch, when nothing could be printed', async () => {
    await open({ show_style: { styles: {}, in_use: 'default', candidate: false } })
    expect(await screen.findByRole('switch', { name: 'Use my own style' })).toBeTruthy()
    expect(screen.queryByRole('img')).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

describe('StyleRow, no style of your own yet', () => {
  it("shows The other door in use, the switch off, and what turning it on does; no other button", async () => {
    await open({})
    const img = await ready()
    expect(img.getAttribute('src')).toBe('door-file://style/default/cv_page_1.png?v=d1')
    expect(screen.getByRole('group', { name: "The other door" }).className).toContain('style-current') // the accent border on it
    expect(screen.getByRole('switch', { name: 'Use my own style' }).getAttribute('aria-checked')).toBe('false')
    expect(screen.getByText(/in the style of your CV file\. Building it takes 2–5 minutes in the background\./)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Use the style of|Use this style|Keep/ })).toBeNull()
  })

  it('turned on, builds from the CV file in main, tells the app, and uses the style once it is ready', async () => {
    const calls: Record<string, unknown>[] = []
    const h = mockDoor({ show_style: shown(), use_style: (a: Record<string, unknown>) => (calls.push(a), { in_use: 'like', prepared: 0 }) })
    const onChanged = vi.fn()
    const { rerender } = render(<StyleRow state="none" canBuild onChanged={onChanged} reload={0} />)
    await ready()
    await userEvent.click(screen.getByRole('switch', { name: 'Use my own style' }))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(h.styleFromCvFile).toHaveBeenCalled()
    expect((await screen.findByRole('switch', { name: 'Use my own style' })).getAttribute('aria-checked')).toBe('true')
    rerender(<StyleRow state="building" canBuild onChanged={onChanged} reload={0} />)
    expect(await screen.findByText('Building your style…')).toBeTruthy()
    rerender(<StyleRow state="building" step={{ message: 'fetching the fonts', done: null, total: null }} canBuild onChanged={onChanged} reload={0} />)
    expect(await screen.findByText('Building your style: getting the fonts…')).toBeTruthy()
    h.call.mockImplementation(async (tool: string, args?: Record<string, unknown>) => ({ ok: true, data: tool === 'show_style' ? both({ candidate: true }) : (calls.push(args ?? {}), { in_use: 'like', prepared: 0 }) }))
    rerender(<StyleRow state="ready" canBuild onChanged={onChanged} reload={0} />)
    await waitFor(() => expect(calls).toEqual([{ style: 'like' }]))
  })

  it('says it is reading the CV file while it is taken in, the switch held', async () => {
    const h = await open({})
    await ready()
    let finish: (v: unknown) => void = () => {}
    h.styleFromCvFile.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)))
    await userEvent.click(screen.getByRole('switch', { name: 'Use my own style' }))
    act(() => h.pushStyleReading())
    expect(await screen.findByText("Reading your CV's look…")).toBeTruthy()
    await userEvent.click(screen.getByRole('switch', { name: 'Use my own style' })) // held while it reads
    expect(h.styleFromCvFile).toHaveBeenCalledTimes(1)
    finish({ ok: true, data: { started: true } })
    await waitFor(() => expect(screen.queryByText("Reading your CV's look…")).toBeNull())
  })

  it('a CV file that cannot be used is named in the error box, and the switch goes back off', async () => {
    const h = await open({})
    await ready()
    h.styleFromCvFile.mockResolvedValueOnce({ ok: false, error: 'Choose your CV file under Sources first.' })
    await userEvent.click(screen.getByRole('switch', { name: 'Use my own style' }))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Choose your CV file under Sources first.')
    expect(alert.className).toBe('error')
    expect(screen.getByRole('switch', { name: 'Use my own style' }).getAttribute('aria-checked')).toBe('false')
    expect(h.onChanged).not.toHaveBeenCalled()
  })

  it('has no switch on made-up data', async () => {
    await open({}, { canBuild: false })
    await ready()
    expect(screen.queryByRole('switch')).toBeNull()
  })

  it('goes back to this, saying nothing, when the build failed', async () => {
    await open({}, { state: 'failed' })
    await ready()
    expect(screen.getByRole('switch', { name: 'Use my own style' }).getAttribute('aria-checked')).toBe('false')
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

describe('StyleRow, a style of your own', () => {
  it("compares the two, the accent border on the one in use, no button under either", async () => {
    await open({ show_style: both({ candidate: true }) }, { state: 'ready' })
    await ready()
    expect(screen.getByRole('img', { name: /Your CV/ }).getAttribute('src')).toBe('door-file://style/like/cv_page_1.png?v=l1')
    expect(screen.getByRole('group', { name: 'Your CV' }).className).not.toContain('style-current')
    expect(screen.getByRole('group', { name: "The other door" }).className).toContain('style-current')
    expect(screen.getAllByRole('button').map((b) => b.getAttribute('aria-label'))).toEqual(["Show The other door in full", 'Show Your CV in full'])
  })

  it('on: use_style like, the app told, the border moved, then the question about the prepared CVs', async () => {
    const calls: Record<string, unknown>[] = []
    let inUse = 'default'
    const h = await open({ show_style: () => both({ in_use: inUse }), use_style: (a: Record<string, unknown>) => (calls.push(a), (inUse = 'like'), { in_use: 'like', prepared: 2 }) })
    await ready()
    await userEvent.click(screen.getByRole('switch', { name: 'Use my own style' }))
    expect(await screen.findByRole('button', { name: 'Print 2 prepared CVs again' })).toBeTruthy()
    expect(calls[0]).toEqual({ style: 'like' })
    expect(h.onChanged).toHaveBeenCalled()
    expect(h.styleFromCvFile).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.getByRole('group', { name: "The other door" }).className).not.toContain('style-current'))
    expect((await screen.findByRole('switch', { name: 'Use my own style' })).getAttribute('aria-checked')).toBe('true')
  })

  it('flips at once, before the server answers, and goes back if the choice fails', async () => {
    let fail: (e: unknown) => void = () => undefined
    await open({ show_style: both(), use_style: () => new Promise((_, reject) => (fail = reject)) })
    await ready()
    const toggle = screen.getByRole('switch', { name: 'Use my own style' })
    await userEvent.click(toggle)
    expect(toggle.getAttribute('aria-checked')).toBe('true')
    expect(screen.getByRole('group', { name: 'Your CV' }).className).toContain('style-current')
    fail({ message: 'config.json is not writable' })
    expect(await screen.findByRole('alert')).toHaveTextContent('config.json is not writable')
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('false'))
  })

  it("off: use_style default, back to The other door", async () => {
    const calls: Record<string, unknown>[] = []
    await open({ show_style: both({ in_use: 'like' }), use_style: (a: Record<string, unknown>) => (calls.push(a), { in_use: 'default', prepared: 0 }) })
    await ready()
    expect((await screen.findByRole('switch', { name: 'Use my own style' })).getAttribute('aria-checked')).toBe('true')
    expect(screen.getByRole('group', { name: "The other door" }).className).not.toContain('style-current')
    await userEvent.click(screen.getByRole('switch', { name: 'Use my own style' }))
    await waitFor(() => expect(calls).toEqual([{ style: 'default' }]))
  })

  it('a choice that fails is said in the error box', async () => {
    await open({ show_style: both({ candidate: true }), use_style: () => { throw { message: 'config.json is not writable' } } }, { state: 'ready' })
    await ready()
    await userEvent.click(screen.getByRole('switch', { name: 'Use my own style' }))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('config.json is not writable')
    expect(alert.className).toBe('error')
  })

  it('a new CV file builds the style again from it, and a style in use takes the new one when ready', async () => {
    const calls: Record<string, unknown>[] = []
    const h = mockDoor({ show_style: both({ in_use: 'like' }), use_style: (a: Record<string, unknown>) => (calls.push(a), { in_use: 'like', prepared: 0 }) })
    const props = { canBuild: true, onChanged: () => undefined, reload: 0 }
    const { rerender } = render(<StyleRow state="none" {...props} replaced={0} />)
    await ready()
    expect(h.styleFromCvFile).not.toHaveBeenCalled()
    rerender(<StyleRow state="none" {...props} replaced={1} />)
    await waitFor(() => expect(h.styleFromCvFile).toHaveBeenCalledTimes(1))
    rerender(<StyleRow state="building" {...props} replaced={1} />)
    h.call.mockImplementation(async (tool: string, args?: Record<string, unknown>) => ({ ok: true, data: tool === 'show_style' ? both({ in_use: 'like', candidate: true }) : (calls.push(args ?? {}), { in_use: 'like', prepared: 0 }) }))
    rerender(<StyleRow state="ready" {...props} replaced={1} />)
    await waitFor(() => expect(calls).toEqual([{ style: 'like' }]))
  })

  it('a new CV file builds nothing while no style of your own was ever made', async () => {
    const h = mockDoor({ show_style: shown() })
    const { rerender } = render(<StyleRow state="none" canBuild onChanged={() => undefined} reload={0} replaced={0} />)
    await ready()
    rerender(<StyleRow state="none" canBuild onChanged={() => undefined} reload={0} replaced={1} />)
    await new Promise((r) => setTimeout(r, 20))
    expect(h.styleFromCvFile).not.toHaveBeenCalled()
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
    await userEvent.click(screen.getByRole('switch', { name: 'Use my own style' }))
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

  it('a print that fails is said in the error box, and the offer stays to try again', async () => {
    let fail = true
    const h = await open({
      show_style: both({ candidate: true }),
      use_style: (a: Record<string, unknown>) => {
        if (!a['rerender']) return { in_use: 'like', prepared: 2 }
        if (fail) throw { message: 'The print stopped. Try again.' }
        return { in_use: 'like', prepared: 2, rerendered: ['a.1', 'a.2'], failed: [] }
      },
    }, { state: 'ready' })
    await ready()
    await userEvent.click(screen.getByRole('switch', { name: 'Use my own style' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Print 2 prepared CVs again' }))
    const alert = await screen.findByRole('alert')
    expect(alert.className).toBe('error')
    fail = false
    await userEvent.click(screen.getByRole('button', { name: 'Print 2 prepared CVs again' }))
    expect(await screen.findByText('2 printed again.')).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(h.call).toHaveBeenCalledWith('use_style', { style: 'like', rerender: true })
  })

  it('says it is busy while it prints', async () => {
    let finish: (v: unknown) => void = () => undefined
    mockDoor({
      show_style: both({ candidate: true }),
      use_style: (a: Record<string, unknown>) => (a['rerender'] ? new Promise((r) => (finish = r)) : { in_use: 'like', prepared: 2 }),
    })
    render(<StyleRow state="ready" canBuild onChanged={() => undefined} reload={0} />)
    await ready()
    await userEvent.click(screen.getByRole('switch', { name: 'Use my own style' }))
    await userEvent.click(await screen.findByRole('button', { name: /Print 2 prepared/ }))
    expect(await screen.findByText('Printing again…')).toBeTruthy()
    finish({ in_use: 'like', prepared: 2, rerendered: ['a.1', 'a.2'], failed: [] })
    expect(await screen.findByText('2 printed again.')).toBeTruthy()
  })

  it('names how many could not be printed, and Try again prints them', async () => {
    let round = 0
    mockDoor({
      show_style: both({ candidate: true }),
      use_style: (a: Record<string, unknown>) =>
        a['rerender'] ? (round++ === 0 ? { in_use: 'like', prepared: 3, rerendered: ['a.1', 'a.2'], failed: [{ job: 'a.3', reason: 'it could not be printed', prepare_again: false }] } : { in_use: 'like', prepared: 3, rerendered: ['a.1', 'a.2', 'a.3'], failed: [] }) : { in_use: 'like', prepared: 3 },
    })
    render(<StyleRow state="ready" canBuild onChanged={() => undefined} reload={0} />)
    await ready()
    await userEvent.click(screen.getByRole('switch', { name: 'Use my own style' }))
    await userEvent.click(await screen.findByRole('button', { name: /Print 3 prepared/ }))
    expect(await screen.findByText('2 printed again.')).toBeTruthy()
    await userEvent.click(await screen.findByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('3 printed again.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
  })
})

describe('StyleRow, an old CV in a two-column style', () => {
  it('says to prepare it again or revise it, with no Try again', async () => {
    mockDoor({
      show_style: both({ candidate: true }),
      use_style: (a: Record<string, unknown>) =>
        a['rerender']
          ? { in_use: 'like', prepared: 2, rerendered: ['a.1'], failed: [{ job: 'a.2', reason: 'this CV has no section kinds: prepare it again or revise it', prepare_again: true }] }
          : { in_use: 'like', prepared: 2 },
    })
    render(<StyleRow state="ready" canBuild onChanged={() => undefined} reload={0} />)
    await ready()
    await userEvent.click(screen.getByRole('switch', { name: 'Use my own style' }))
    await userEvent.click(await screen.findByRole('button', { name: /Print 2 prepared/ }))
    expect(await screen.findByText('1 printed again.')).toBeTruthy()
    expect(await screen.findByText(/prepare it again or revise it/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
  })

  it('keeps the switch where it is when the CV could not be read for the previews', async () => {
    await open({ show_style: { styles: {}, in_use: 'like', candidate: false, warning: 'Claude could not read your CV' } })
    expect((await screen.findByRole('switch', { name: 'Use my own style' })).getAttribute('aria-checked')).toBe('true')
  })
})

describe('StyleRow, the full pages', () => {
  it('opens a style in a dialog to read, CV and letter, and closes with Escape', async () => {
    await open({ show_style: both() })
    await ready()
    await userEvent.click(screen.getByRole('button', { name: 'Show Your CV in full' }))
    const dialog = await screen.findByRole('dialog', { name: 'Your CV' })
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
    expect(screen.getByRole('img', { name: /The other door/ })).toBeTruthy()
    expect(screen.queryByText('Preparing the previews…')).toBeNull()
  })
})
