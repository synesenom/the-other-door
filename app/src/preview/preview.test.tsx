// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { App } from '../renderer/App'
import { stubNarrow } from '../renderer/testing'
import { createMockDoor } from './mock-door'
import { Guide } from './Guide'
import { pressInOrder } from './press'
import { DATA_STATES, readSelection, sceneById, SCENES } from './scenes'

beforeEach(() => stubNarrow(false))
afterEach(cleanup)

function mount(sceneId: string, state: (typeof DATA_STATES)[number] = 'ok') {
  const scene = sceneById(sceneId)!
  window.door = createMockDoor(scene, state, { delayMs: 0 })
  return render(<App start={scene.start} />)
}

describe('readSelection', () => {
  it('is null without a known scene: the list of scenes opens', () => {
    expect(readSelection(new URLSearchParams(''))).toBeNull()
    expect(readSelection(new URLSearchParams('scene=nope'))).toBeNull()
  })
  it('reads the scene, and an unknown state is the normal one', () => {
    expect(readSelection(new URLSearchParams('scene=matches&state=empty'))).toMatchObject({ scene: { id: 'matches' }, state: 'empty' })
    expect(readSelection(new URLSearchParams('scene=matches&state=odd'))).toMatchObject({ state: 'ok' })
  })
})

describe('createMockDoor', () => {
  const door = (state: (typeof DATA_STATES)[number]) => createMockDoor(sceneById('matches')!, state, { delayMs: 0 })

  it('answers the lists from the fixtures, or empty in the empty state', async () => {
    expect(await door('ok').call('list_matches')).toMatchObject({ ok: true, data: { matches: expect.arrayContaining([expect.objectContaining({ id: 'jobindex.demo-1' })]) } })
    expect(await door('empty').call('list_matches')).toMatchObject({ ok: true, data: { matches: [] } })
  })
  it('answers a data tool with an error in the error state, but not the sidebar\'s', async () => {
    const d = door('error')
    expect(await d.call('list_matches')).toMatchObject({ ok: false })
    expect(await d.call('status_summary')).toMatchObject({ ok: true })
  })
  it('never answers a data tool in the loading state', async () => {
    const answer = door('loading').call('list_matches')
    const first = await Promise.race([answer, new Promise((r) => setTimeout(() => r('waiting'), 20))])
    expect(first).toBe('waiting')
  })
  it('lets the app past its first read of the profile in every state, then not', async () => {
    const d = door('error')
    await d.info()
    expect(await d.call('show_profile')).toMatchObject({ ok: true })
    expect(await d.call('show_profile')).toMatchObject({ ok: false })
  })
  it('does not hand out a second free read when the app starts twice (StrictMode)', async () => {
    const d = door('error')
    await d.info()
    await d.info()
    expect(await d.call('show_profile')).toMatchObject({ ok: true })
    expect(await d.call('show_profile')).toMatchObject({ ok: false })
  })
  it('says nothing is new in the empty state', async () => {
    expect(await door('empty').call('status_summary')).toMatchObject({ data: { since_last_review: { new_matches: 0 } } })
  })
  it('never answers the tool a scene holds on', async () => {
    const d = createMockDoor(sceneById('onboarding-reading-last')!, 'ok', { delayMs: 0 })
    const first = await Promise.race([d.call('keywords'), new Promise((r) => setTimeout(() => r('waiting'), 20))])
    expect(first).toBe('waiting')
  })
  it('makes long titles and many rows in the long state, each of which opens', async () => {
    const d = door('long')
    const base = await door('ok').call('list_matches')
    const long = await d.call('list_matches')
    if (!base.ok || !long.ok) throw new Error('no answer')
    const rows = (long.data as { matches: { id: string; title: string }[] }).matches
    expect(rows.length).toBeGreaterThan((base.data as { matches: unknown[] }).matches.length)
    expect(rows[0].title.length).toBeGreaterThan(60)
    expect(await d.call('show', { job_id: rows[rows.length - 1].id })).toMatchObject({ ok: true })
  })
})

describe('the visual guide', () => {
  it('shows every kind of button, enabled and disabled', () => {
    render(<Guide />)
    for (const kind of ['primary', 'secondary', 'quiet']) {
      expect(document.querySelectorAll(`button.${kind}:not(.sidebar-problem)`)).toHaveLength(2)
      expect(document.querySelector(`button.${kind}:disabled`)).not.toBeNull()
    }
  })
})

describe('the plan line', () => {
  it('says the window is nearly full, as plain text that opens nothing', async () => {
    mount('matches', 'plan-low')
    const line = await screen.findByText(/Claude can prepare 2 more, resets/)
    expect(line.closest('button')).toBeNull()
    expect(line.closest('p')).not.toBeNull()
  })

  it('says nothing with room to spare', async () => {
    const { container } = mount('matches')
    await waitFor(() => expect(container.querySelector('main')).toBeInTheDocument())
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByText(/Claude can prepare/)).toBeNull()
  })

  it('reads the summary again when a Prepare ends', async () => {
    const scene = sceneById('matches')!
    const door = createMockDoor(scene, 'ok', { delayMs: 0 })
    let reads = 0
    const call = door.call.bind(door)
    window.door = { ...door, call: (tool: string, args?: Record<string, unknown>) => { if (tool === 'status_summary') reads++; return call(tool, args) } } as typeof door
    render(<App start={scene.start} />)
    await waitFor(() => expect(reads).toBeGreaterThan(0))
    const before = reads
    const { preparing, preparingChanged } = await import('../renderer/screens/prepare-store')
    act(() => { preparing.set('a', { since: 0, message: '' }); preparingChanged() })
    act(() => { preparing.delete('a'); preparingChanged() })
    await waitFor(() => expect(reads).toBeGreaterThan(before))
  })
})

describe('scenes', () => {
  it('have unique ids', () => {
    expect(new Set(SCENES.map((s) => s.id)).size).toBe(SCENES.length)
  })

  // A fixture a screen can no longer read fails here, not in a browser later.
  describe.each(SCENES.filter((s) => s.id !== 'splash' && !s.guide).map((s) => s.id))('%s', (id) => {
    it.each(DATA_STATES)('renders in the %s state', async (state) => {
      const { container } = mount(id, state)
      await waitFor(() => expect(container.querySelector('main')).toBeInTheDocument())
      await new Promise((r) => setTimeout(r, 20))
      expect(container.querySelector('main')).toBeInTheDocument()
    })
  })

  it.each([
    ['applications', 'Applications'],
    ['profile', 'Profile'],
    ['settings', 'Settings'],
  ])('%s opens on its destination', async (id, name) => {
    mount(id)
    await waitFor(() => expect(screen.getByRole('button', { name })).toHaveAttribute('aria-current', 'page'))
  })

  it('applications shows a card with no answer and its Mark ghosted', async () => {
    mount('applications')
    expect(await screen.findByRole('button', { name: /^Accounting Manager/ })).toHaveTextContent('No answer in 45 days')
    expect(screen.getByRole('button', { name: 'Mark ghosted' })).toBeInTheDocument()
  })

  it('profile-stories lists the stories', async () => {
    mount('profile-stories')
    expect(await screen.findByRole('listitem', { name: 'Rebuilt the cash forecast at Acme Foods' })).toBeInTheDocument()
  })

  it('onboarding-review-style offers the CV style, off', async () => {
    mount('onboarding-review-style')
    expect(await screen.findByRole('checkbox', { name: 'Make my tailored CVs look like the CV I uploaded' })).not.toBeChecked()
  })

  it('matches-style-ready says at the sidebar\'s foot that the style is ready', async () => {
    mount('matches-style-ready')
    expect(await screen.findByRole('button', { name: 'Your CV style is ready to compare' })).toBeInTheDocument()
  })

  it('sent opens what was sent, read only', async () => {
    mount('sent')
    expect(await screen.findByRole('heading', { name: 'What you sent' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Revise' })).toBeNull()
  })

  it.each(DATA_STATES)('splash stays on the splash in the %s state', async (state) => {
    const { container } = mount('splash', state)
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.getByRole('status', { name: 'Starting The other door' })).toBeInTheDocument()
    expect(container.querySelector('main')).not.toBeInTheDocument()
  })

  it('analytics shows the interview rate, and in the empty state one line', async () => {
    mount('analytics')
    const part = await screen.findByRole('region', { name: 'Applications' })
    expect(part).toHaveTextContent('of your applications with an outcome (an interview, a rejection or no reply) led to an interview: 6 of 12, likely between 36% and 64%.')
    expect(part).toHaveTextContent('Best-scored matches: 5 of 6 led to an interview, likely between 65% and 94%.')
    expect(part).toHaveTextContent('Matches near your minimum score led to an interview less often: consider raising it.')
    expect(within(part).queryAllByRole('img')).toEqual([])
    const market = await screen.findByRole('region', { name: 'Market' })
    expect(await within(market).findByRole('listitem', { name: 'IFRS, in your CV' })).toHaveTextContent('46% of the ads')
    expect(within(market).getByRole('listitem', { name: 'SAP, not in your CV' })).toBeInTheDocument()
    cleanup()
    mount('analytics', 'empty')
    expect(await screen.findByText('Your interview rate shows here once an application has an outcome.')).toBeInTheDocument()
    expect(await screen.findByText('The market shows here once ads are read.')).toBeInTheDocument()
  })

  it('posting opens the posting', async () => {
    mount('posting')
    expect(await screen.findByRole('heading', { name: 'Senior Financial Controller' })).toBeInTheDocument()
  })

  it('posting: Prepare ends on the prepared CV and letter, as the server would', async () => {
    mount('posting')
    ;(await screen.findByRole('button', { name: 'Prepare application' })).click()
    expect(await screen.findByRole('button', { name: '← Posting' })).toBeInTheDocument()
    expect(screen.queryByText('There is nothing prepared for this job yet.')).toBeNull()
  })

  it("materials: I've applied records it and says so, as the server would", async () => {
    mount('materials')
    ;(await screen.findByRole('button', { name: "I've applied" })).click()
    expect(await screen.findByText(/Applied: .*It is in Applications now\./)).toBeInTheDocument()
  })

  it('finding-summary opens on the run summary with no run started', async () => {
    const { container } = mount('finding-summary')
    await waitFor(() => expect(container.querySelector('main')).toHaveTextContent(/Group Controller/))
  })

  it('finding-summary-none says the run in a line and offers the next steps', async () => {
    mount('finding-summary-none')
    expect(await screen.findByText('46 jobs found, 40 close enough to score, none reached your bar (65%)')).toBeInTheDocument()
    for (const name of ['Lower the bar', 'Check your search terms']) expect(screen.getByRole('button', { name })).toBeInTheDocument()
  })

  it('finding-first-run reminds about the discovery sources left off', async () => {
    mount('finding-first-run')
    expect(await screen.findByRole('note', { name: 'Employer discovery' })).toHaveTextContent(/can also find employers on LinkedIn, by reading/)
  })

  it('onboarding-review opens the wizard on its last step', async () => {
    mount('onboarding-review')
    await waitFor(() => expect(screen.getByLabelText('Step 3 of 3')).toHaveAttribute('aria-current', 'step'))
    expect(screen.getByDisplayValue('Jane Doe')).toBeInTheDocument()
  })

  it('onboarding-sources opens the wizard on its first step', async () => {
    mount('onboarding-sources')
    await waitFor(() => expect(screen.getByLabelText('Step 1 of 3')).toHaveAttribute('aria-current', 'step'))
  })

  it('profile-cv-style-loading holds the sheet and says the previews are being made', async () => {
    mount('profile-cv-style-loading')
    expect(await screen.findByText('Preparing the previews…')).toBeInTheDocument()
  })

  it('profile-cv-style-building keeps the sheet and says the build runs', async () => {
    mount('profile-cv-style-building')
    expect(await screen.findByText('Building your style…')).toBeInTheDocument()
    expect(screen.getAllByRole('img', { name: /first page/ })).toHaveLength(1)
  })

  it('profile-cv-style-candidate chooses the new style, then offers to print the prepared CVs again', async () => {
    mount('profile-cv-style-candidate')
    await userEvent.click(await screen.findByRole('button', { name: 'Use this style' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Print 2 prepared CVs again' }))
    expect(await screen.findByText('2 printed again.')).toBeInTheDocument()
  })

  it('profile-cv-style-printed shows the count printed again and, for the one that failed, Try again', async () => {
    mount('profile-cv-style-printed')
    await pressInOrder(sceneById('profile-cv-style-printed')!.press!)
    expect(await screen.findByText('2 printed again.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('3 printed again.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
  })

  it('profile-cv-style-earlier can keep the style in use', async () => {
    mount('profile-cv-style-earlier')
    await userEvent.click(await screen.findByRole('button', { name: 'Keep my current style' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Use this style' })).toBeNull())
    expect(screen.getByText('In use')).toBeInTheDocument()
  })

  it('profile-cv-style-inuse opens the full pages of a style, and goes back to The other door\'s', async () => {
    mount('profile-cv-style-inuse')
    await userEvent.click(await screen.findByRole('button', { name: 'Show Like your CV in full' }))
    expect(within(await screen.findByRole('dialog', { name: 'Like your CV' })).getAllByRole('img')).toHaveLength(2)
    await userEvent.keyboard('{Escape}')
    await userEvent.click(screen.getByRole('button', { name: "Use The other door's" }))
    await waitFor(() => expect(within(screen.getByRole('group', { name: "The other door's" })).getByText('In use')).toBeInTheDocument())
  })

  it('profile-cv-style-two-column says what two columns may cost', async () => {
    mount('profile-cv-style-two-column')
    expect(await screen.findByText('Some application systems read two-column CVs less well.')).toBeInTheDocument()
  })

  it('profile-cv starts a build, which ends with a style to compare', async () => {
    mount('profile-cv')
    await userEvent.click(await screen.findByRole('button', { name: 'Use the style of my CV…' }))
    expect(await screen.findByText('Building your style…')).toBeInTheDocument()
  })
})
