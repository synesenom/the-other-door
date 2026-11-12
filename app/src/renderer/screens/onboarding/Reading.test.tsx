// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { act, StrictMode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../../testing'
import { Reading } from './Reading'
import { existingProfile, Host } from './testing'
import type { WizardState } from './reducer'

afterEach(cleanup)

const titles = { titles: [{ title: 'Lead', reason: 'you led', recommended: true }, { title: 'Quant', reason: 'maths', recommended: false }] }
const basics = { name: 'Ada', email: 'ada@x.dk', location: 'Aarhus', languages: ['English', 'Danish'], remote: 'hybrid', missing: [] }
const draft = { markdown: '# Ada\n', provenance: [], todos: [], sources: [] }
const proposal = { keywords: ['lead'], topic_terms: ['data'] }

let seen: WizardState
function setup(handlers: Record<string, unknown> = {}, start: Partial<WizardState> = { urls: ['https://ada.dev'], step: 'reading' }, profile?: typeof existingProfile, strict = false) {
  const h = mockDoor({ draft_cv: draft, infer_basics: basics, suggest_titles: titles, keywords: proposal, ...handlers })
  const onDone = vi.fn()
  const onBack = vi.fn()
  const host = (
    <Host profile={profile} start={start}>
      {(state, dispatch) => {
        seen = state
        return <Reading state={state} dispatch={dispatch} onDone={onDone} onBack={onBack} />
      }}
    </Host>
  )
  render(strict ? <StrictMode>{host}</StrictMode> : host)
  return { ...h, onDone, onBack }
}
const tools = (h: ReturnType<typeof setup>) => h.call.mock.calls.map((c) => c[0])

describe('Reading', () => {
  const turning = () => document.querySelectorAll('.step-working .step-mark').length

  it('the running step shows its time so far', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      setup({ draft_cv: () => new Promise(() => undefined) })
      await screen.findByRole('heading', { name: 'Drafting your CV' })
      await act(async () => vi.advanceTimersByTime(80_000))
      expect(screen.getByText('1 min 20 s')).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('the ring of the running step turns while Claude is at work', async () => {
    setup({ draft_cv: () => new Promise(() => undefined) })
    expect(await screen.findByRole('heading', { name: 'Drafting your CV' })).toBeInTheDocument()
    expect(turning()).toBe(1)
  })

  it('numbers its steps like the run screen: the running one in its ring, the ones to come faded', async () => {
    setup({ draft_cv: () => new Promise(() => undefined) })
    await screen.findByRole('heading', { name: 'Drafting your CV' })
    const steps = within(screen.getByRole('list', { name: 'Reading' })).getAllByRole('listitem')
    expect(steps.map((li) => li.querySelector('.step-mark')!.textContent)).toEqual(['1', '2', '3', '4', '5'])
    expect(steps.map((li) => li.classList.contains('step-waiting'))).toEqual([false, true, true, true, true])
  })

  it('a failed draft stops the ring', async () => {
    setup({ draft_cv: () => { throw new Error('no') } })
    await screen.findByRole('alert')
    expect(turning()).toBe(0)
  })

  it('draft, basics, titles, terms and an example story, then on to the review, asking nothing', async () => {
    const story = { title: 'Halved the close', context: 'c', action: 'a', result: 'r', learning: '', missing: ['learning'], conflicts: [] }
    const h = setup({ draft_stories: { outcome: 'proposed', stories: [story] } })
    expect(screen.getByRole('list', { name: 'Reading' })).toBeInTheDocument()
    await waitFor(() => expect(h.onDone).toHaveBeenCalled())
    expect(h.draftCv).toHaveBeenCalledWith({ files: [], urls: ['https://ada.dev'] })
    expect(tools(h)).toEqual(['draft_stories', 'infer_basics', 'suggest_titles', 'keywords'])
    expect(h.call).toHaveBeenCalledWith('draft_stories', { from_cv: true })
    expect(seen.story).toEqual({ values: { title: 'Halved the close', context: 'c', action: 'a', result: 'r', learning: '' }, keep: true })
    expect(h.call).toHaveBeenCalledWith('infer_basics', { markdown: '# Ada\n'  })
    expect(h.call).toHaveBeenCalledWith('suggest_titles', { titles: [], languages: ['English', 'Danish'] })
    expect(h.call).toHaveBeenCalledWith('keywords', { role_targets: ['Lead'], languages: ['English', 'Danish'] })
    expect(seen.name).toBe('Ada')
    expect(seen.roleTargets).toEqual(['Lead'])
    expect(seen.cvText).toBe('# Ada\n')
    expect(seen.keywords).toEqual(['lead'])
    expect(screen.queryByRole('textbox')).toBeNull()
  })

  it('goes on to the review under StrictMode too (the dev build mounts it twice), reading once', async () => {
    const h = setup({}, undefined, undefined, true)
    await waitFor(() => expect(h.onDone).toHaveBeenCalled())
    expect(h.draftCv).toHaveBeenCalledTimes(1)
    expect(seen.name).toBe('Ada')
  })

  it('goes on to the review with what it could not find, asking nothing', async () => {
    const h = setup({ infer_basics: { ...basics, name: null, location: null, missing: ['name', 'location'] } })
    await waitFor(() => expect(h.onDone).toHaveBeenCalled())
    expect(seen.missing).toEqual(['name', 'location'])
    expect(screen.queryByLabelText('Your name')).toBeNull()
  })

  it('a failed basics call leaves them for the review, and says why', async () => {
    const h = setup({ infer_basics: () => { throw new Error('not logged in') } })
    await waitFor(() => expect(h.onDone).toHaveBeenCalled())
    expect(seen.missing).toEqual(['name', 'email', 'location'])
    expect(seen.warnings.basics).toBe('not logged in')
  })

  it('what Claude could not do is kept for the review: details, titles, terms', async () => {
    const h = setup({ infer_basics: { ...basics, warning: 'usage limit' }, suggest_titles: { ...titles, warning: 'overloaded' }, keywords: () => { throw new Error('quota') } })
    await waitFor(() => expect(h.onDone).toHaveBeenCalled())
    expect(seen.warnings).toEqual({ basics: 'usage limit', titles: 'overloaded', terms: 'quota' })
  })

  it('a failed titles call says why', async () => {
    const h = setup({ suggest_titles: () => { throw new Error('boom') } })
    await waitFor(() => expect(h.onDone).toHaveBeenCalled())
    expect(seen.warnings.titles).toBe('boom')
  })

  it('left with Back, it stops: a late answer lands nowhere and nothing more is asked', async () => {
    let finish: (v: unknown) => void = () => undefined
    const h = mockDoor({ draft_cv: () => new Promise((r) => { finish = r }), infer_basics: basics, suggest_titles: titles, keywords: proposal })
    const onDone = vi.fn()
    const view = (reading: boolean) => (
      <Host start={{ urls: ['https://ada.dev'], step: 'reading' }}>
        {(state, dispatch) => {
          seen = state
          return reading ? <Reading state={state} dispatch={dispatch} onDone={onDone} onBack={() => undefined} /> : null
        }}
      </Host>
    )
    const { rerender } = render(view(true))
    await waitFor(() => expect(h.draftCv).toHaveBeenCalled())
    rerender(view(false))
    await act(async () => finish(draft))
    expect(h.call).not.toHaveBeenCalled()
    expect(seen.cvText).toBeNull()
    expect(onDone).not.toHaveBeenCalled()
  })

  it('no titles: chooses no terms, and leaves the titles for the review', async () => {
    const h = setup({ suggest_titles: { titles: [], warning: 'no' } })
    await waitFor(() => expect(h.onDone).toHaveBeenCalled())
    expect(tools(h)).not.toContain('keywords')
    expect(seen.missing).toEqual(['titles'])
  })

  it('a failed titles call goes on too', async () => {
    const h = setup({ suggest_titles: () => { throw new Error('boom') } })
    await waitFor(() => expect(h.onDone).toHaveBeenCalled())
    expect(seen.missing).toEqual(['titles'])
  })

  it('failed terms: the titles stand in, and it still goes on', async () => {
    const h = setup({ keywords: () => { throw new Error('quota') } })
    await waitFor(() => expect(h.onDone).toHaveBeenCalled())
    expect(seen.keywordsState).toBe('skipped')
  })

  it('names a file it found no text in, while it reads on', async () => {
    setup({
      draft_cv: { ...draft, sources: [{ source: 'scan.pdf', kind: 'file', chars: 0 }, { source: 'cv.txt', kind: 'file', chars: 900 }] },
      infer_basics: () => new Promise(() => {}),
    })
    expect(await screen.findByText('scan.pdf: no text found in this file (a scanned PDF?)')).toBeInTheDocument()
    expect(screen.queryByText(/cv\.txt: no text/)).toBeNull()
  })

  it('a failed draft says so: try again, or go on without one', async () => {
    let tries = 0
    const h = setup({ draft_cv: () => { tries += 1; throw new Error('bad pdf') } })
    expect(await screen.findByRole('alert')).toHaveTextContent('bad pdf')
    expect(tools(h)).not.toContain('infer_basics')
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(tries).toBe(2))
    await userEvent.click(await screen.findByRole('button', { name: 'Go on without a draft' }))
    await waitFor(() => expect(tools(h)).toContain('infer_basics'))
    expect(h.call).toHaveBeenCalledWith('infer_basics', {})
  })

  it('no sources: no draft, and the review asks the rest', async () => {
    const h = setup({ infer_basics: { ...basics, name: null, email: null, location: null, missing: ['name', 'email', 'location'] } }, { step: 'reading' })
    await waitFor(() => expect(h.onDone).toHaveBeenCalled())
    expect(h.draftCv).not.toHaveBeenCalled()
  })

  it('a redo keeps its answers and offers new titles', async () => {
    const h = setup({}, { urls: ['https://ada.dev'], step: 'reading' }, existingProfile)
    await waitFor(() => expect(h.onDone).toHaveBeenCalled())
    expect(seen.name).toBe('Ada Lovelace')
    expect(h.call).toHaveBeenCalledWith('suggest_titles', { titles: ['Data Scientist'], languages: ['English'] })
    expect(seen.roleTargets).toEqual(['Data Scientist', 'Lead'])
    expect(seen.titles.map((t) => t.title)).toEqual(['Lead', 'Quant'])
  })

  describe('the example story', () => {
    it('one that cannot be drafted is said nowhere: the review goes without it', async () => {
      const h = setup({ draft_stories: () => { throw new Error('claude timed out') } })
      await waitFor(() => expect(h.onDone).toHaveBeenCalled())
      expect(seen.story).toBeNull()
      expect(screen.queryByRole('alert')).toBeNull()
    })

    it('is not drafted on a redo, nor without sources', async () => {
      const redo = setup({}, { urls: ['https://ada.dev'], step: 'reading' }, existingProfile)
      await waitFor(() => expect(redo.onDone).toHaveBeenCalled())
      expect(tools(redo)).not.toContain('draft_stories')
      expect(within(screen.getByRole('list', { name: 'Reading' })).getAllByRole('listitem')).toHaveLength(4)
      cleanup()
      const bare = setup({}, { step: 'reading' })
      await waitFor(() => expect(bare.onDone).toHaveBeenCalled())
      expect(tools(bare)).not.toContain('draft_stories')
    })

    it('waits for the story when it is the last to come, on its own step', async () => {
      let answer: (v: unknown) => void = () => undefined
      const h = setup({ draft_stories: () => new Promise((r) => (answer = r)) })
      expect(await screen.findByRole('heading', { name: 'Writing an example story' })).toBeInTheDocument()
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Writing an example story' }).closest('li')).toHaveAttribute('aria-current', 'step'))
      expect(h.onDone).not.toHaveBeenCalled()
      await act(async () => answer({ outcome: 'nothing_new', stories: [] }))
      await waitFor(() => expect(h.onDone).toHaveBeenCalled())
      expect(seen.story).toBeNull()
    })
  })
})
