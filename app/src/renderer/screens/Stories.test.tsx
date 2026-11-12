// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { mockDoor } from '../testing'
import { Stories } from './Stories'

afterEach(cleanup)

const story = (title: string, extra: Record<string, unknown> = {}) => ({ title, context: `${title} C`, action: `${title} A`, result: `${title} R`, learning: `${title} X`, ...extra })
const BANK = { path: '/p/story_bank.md', exists: true, stories: [story('Cut build time'), story('Ran the migration')] }

function show(handlers: Record<string, unknown> = {}) {
  const h = mockDoor({ list_stories: BANK, save_story: { outcome: 'added' }, remove_story: { outcome: 'removed' }, ...handlers })
  render(<Stories />)
  return h
}
const row = async (title: string) => within(await screen.findByRole('listitem', { name: title }))
const fill = async (user: ReturnType<typeof userEvent.setup>, values: Record<string, string>, scope = screen) => {
  for (const [label, value] of Object.entries(values)) {
    const box = scope.getByLabelText(label)
    await user.clear(box)
    await user.type(box, value)
  }
}

describe('Stories', () => {
  it('reads only the bank on mount and lists the stories', async () => {
    const { call } = show()
    await row('Cut build time')
    expect(call.mock.calls.map((c) => c[0])).toEqual(['list_stories'])
    expect((await row('Cut build time')).getByText('Cut build time R')).toBeInTheDocument()
    expect(screen.getByText('Ran the migration')).toBeInTheDocument()
  })

  it('says so when the bank is empty', async () => {
    show({ list_stories: { ...BANK, stories: [] } })
    expect(await screen.findByText(/No stories yet/)).toBeInTheDocument()
  })

  it('edits a story and saves it by its old title, renamed', async () => {
    const user = userEvent.setup()
    const { call } = show()
    await user.click((await row('Cut build time')).getByRole('button', { name: 'Edit' }))
    await fill(user, { Title: 'Cut build time by half', Result: 'Ten minutes.' })
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(call).toHaveBeenCalledWith('save_story', expect.objectContaining({ title: 'Cut build time by half', result: 'Ten minutes.', replace: 'Cut build time' })))
  })

  it('asks before removing, then removes', async () => {
    const user = userEvent.setup()
    const { call } = show()
    await user.click((await row('Ran the migration')).getByRole('button', { name: 'Remove' }))
    expect(call.mock.calls.some((c) => c[0] === 'remove_story')).toBe(false)
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(call).toHaveBeenCalledWith('remove_story', { title: 'Ran the migration' }))
  })

  it('drafts from text, shows the draft, and needs the empty fields filled', async () => {
    const user = userEvent.setup()
    const { call } = show({ draft_stories: { outcome: 'proposed', stories: [{ ...story('Drafted'), learning: '', missing: ['learning'], conflicts: ['You wrote 50%; your CV says 30%.'] }] } })
    await user.click(await screen.findByRole('button', { name: 'Write a story' }))
    await user.type(screen.getByLabelText('What did you do?'), 'I drafted something.')
    await user.click(screen.getByRole('button', { name: 'Draft it' }))
    await screen.findByRole('region', { name: 'Drafted stories' })
    expect(call).toHaveBeenCalledWith('draft_stories', { text: 'I drafted something.' })
    expect(screen.getByText(/Still to fill in: learning/)).toBeInTheDocument()
    expect(screen.getByText(/Differs from your CV: You wrote 50%/)).toBeInTheDocument()
    const save = screen.getByRole('button', { name: 'Save 1 story' })
    expect(save).toBeDisabled()
    await user.type(screen.getByLabelText('Drafted: Learning'), 'Learned.')
    await user.click(save)
    await waitFor(() => expect(call).toHaveBeenCalledWith('save_story', expect.objectContaining({ title: 'Drafted', learning: 'Learned.' })))
  })

  it('saves only the ticked drafts, one call each', async () => {
    const user = userEvent.setup()
    const { call } = show({ draft_stories: { outcome: 'proposed', stories: [story('One'), story('Two'), story('Three')] } })
    await user.click(await screen.findByRole('button', { name: 'Write a story' }))
    await user.type(screen.getByLabelText('What did you do?'), 'Three things.')
    await user.click(screen.getByRole('button', { name: 'Draft it' }))
    await screen.findByRole('region', { name: 'Drafted stories' })
    expect(call).toHaveBeenCalledWith('draft_stories', { text: 'Three things.' })
    await user.click(screen.getByRole('checkbox', { name: 'Keep Two' }))
    await user.click(screen.getByRole('button', { name: 'Save 2 stories' }))
    await waitFor(() => expect(call.mock.calls.filter((c) => c[0] === 'save_story').map((c) => (c[1] as { title: string }).title)).toEqual(['One', 'Three']))
  })

  it('an empty bank offers only writing a story, never a draft from the CV', async () => {
    show({ list_stories: { ...BANK, stories: [] } })
    expect(await screen.findByText(/No stories yet/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Write a story' })).toHaveClass('primary')
    expect(screen.queryByRole('button', { name: /from my CV/ })).toBeNull()
  })

  it('says when the text has nothing new', async () => {
    const user = userEvent.setup()
    show({ draft_stories: { outcome: 'nothing_new', stories: [] } })
    await user.click(await screen.findByRole('button', { name: 'Write a story' }))
    await user.type(screen.getByLabelText('What did you do?'), 'Same as before.')
    await user.click(screen.getByRole('button', { name: 'Draft it' }))
    expect(await screen.findByText('Nothing new to propose.')).toBeInTheDocument()
  })

  it('shows a tool error inline and keeps the form', async () => {
    const user = userEvent.setup()
    show({
      save_story: () => {
        throw new Error('a story titled x is already in the bank')
      },
    })
    await user.click((await row('Cut build time')).getByRole('button', { name: 'Edit' }))
    await fill(user, { Title: 'Ran the migration' })
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already in the bank')
    expect(screen.getByLabelText('Title')).toHaveValue('Ran the migration')
  })
})
