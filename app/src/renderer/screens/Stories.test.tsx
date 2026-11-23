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
  it('lists the stories on opening, drafting or saving nothing', async () => {
    const { call } = show()
    await row('Cut build time')
    for (const tool of ['draft_stories', 'save_story', 'remove_story']) expect(call).not.toHaveBeenCalledWith(tool, expect.anything())
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
    await user.click((await row('Cut build time')).getByRole('button', { name: 'Edit…' }))
    await fill(user, { Title: 'Cut build time by half', Result: 'Ten minutes.' })
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(call).toHaveBeenCalledWith('save_story', expect.objectContaining({ title: 'Cut build time by half', result: 'Ten minutes.', replace: 'Cut build time' })))
  })

  it('asks before removing, then removes', async () => {
    const user = userEvent.setup()
    const { call } = show()
    await user.click((await row('Ran the migration')).getByRole('button', { name: 'Remove…' }))
    expect(call.mock.calls.some((c) => c[0] === 'remove_story')).toBe(false)
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(call).toHaveBeenCalledWith('remove_story', { title: 'Ran the migration' }))
  })

  it('drafts from text in the same dialog: the story in its four parts, saved, then the list again', async () => {
    const user = userEvent.setup()
    const { call } = show({ draft_stories: { outcome: 'proposed', stories: [{ ...story('Drafted'), learning: '', missing: ['learning'], conflicts: ['You wrote 50%; your CV says 30%.'] }] } })
    await user.click(await screen.findByRole('button', { name: 'Write a story…' }))
    await user.type(screen.getByLabelText('What did you do?'), 'I drafted something.')
    await user.click(screen.getByRole('button', { name: 'Draft it' }))
    const dialog = within(await screen.findByRole('dialog', { name: 'Your story' }))
    expect(call).toHaveBeenCalledWith('draft_stories', { text: 'I drafted something.' })
    // one story, edited like any other: plain labels, no ticks, the bank's list not editable behind it
    expect(dialog.getByLabelText('Title')).toHaveValue('Drafted')
    expect(dialog.getByLabelText('Context')).toHaveValue('Drafted C')
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(screen.queryByRole('region', { name: 'Drafted stories' })).toBeNull()
    expect(dialog.getByText(/Still to fill in: learning/)).toBeInTheDocument()
    expect(dialog.getByText(/Differs from your CV: You wrote 50%/)).toBeInTheDocument()
    const save = dialog.getByRole('button', { name: 'Save' })
    expect(save).toBeDisabled()
    await user.type(dialog.getByLabelText('Learning'), 'Learned.')
    await user.click(save)
    await waitFor(() => expect(call).toHaveBeenCalledWith('save_story', expect.objectContaining({ title: 'Drafted', learning: 'Learned.' })))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(screen.getByText('Added Drafted.')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Your stories' })).toBeInTheDocument()
  })

  it('shows only the one story the text tells, never the others of an answer', async () => {
    const user = userEvent.setup()
    const { call } = show({ draft_stories: { outcome: 'proposed', stories: [story('One'), story('Two')] } })
    await user.click(await screen.findByRole('button', { name: 'Write a story…' }))
    await user.type(screen.getByLabelText('What did you do?'), 'One thing.')
    await user.click(screen.getByRole('button', { name: 'Draft it' }))
    const dialog = within(await screen.findByRole('dialog', { name: 'Your story' }))
    expect(dialog.getByLabelText('Title')).toHaveValue('One')
    expect(screen.queryByDisplayValue('Two')).toBeNull()
    await user.click(dialog.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(call.mock.calls.filter((c) => c[0] === 'save_story').map((c) => (c[1] as { title: string }).title)).toEqual(['One'])
  })

  it('Cancel on the drafted story saves nothing and goes back to the list', async () => {
    const user = userEvent.setup()
    const { call } = show({ draft_stories: { outcome: 'proposed', stories: [story('One')] } })
    await user.click(await screen.findByRole('button', { name: 'Write a story…' }))
    await user.type(screen.getByLabelText('What did you do?'), 'One thing.')
    await user.click(screen.getByRole('button', { name: 'Draft it' }))
    await user.click(within(await screen.findByRole('dialog', { name: 'Your story' })).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(call.mock.calls.some((c) => c[0] === 'save_story')).toBe(false)
    expect(screen.getByRole('list', { name: 'Your stories' })).toBeInTheDocument()
  })

  it('an empty bank offers only writing a story, never a draft from the CV', async () => {
    show({ list_stories: { ...BANK, stories: [] } })
    expect(await screen.findByText(/No stories yet/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Write a story…' })).toHaveClass('secondary')
    expect(screen.queryByRole('button', { name: /from my CV/ })).toBeNull()
  })

  it('says when the text has nothing new', async () => {
    const user = userEvent.setup()
    show({ draft_stories: { outcome: 'nothing_new', stories: [] } })
    await user.click(await screen.findByRole('button', { name: 'Write a story…' }))
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
    await user.click((await row('Cut build time')).getByRole('button', { name: 'Edit…' }))
    await fill(user, { Title: 'Ran the migration' })
    await user.click(screen.getByRole('button', { name: 'Save' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('already in the bank')
    expect(alert).toHaveClass('error')
    expect(screen.getByLabelText('Title')).toHaveValue('Ran the migration')
  })

  it('a draft that failed is said in the dialog, the text kept to try again', async () => {
    const user = userEvent.setup()
    show({
      draft_stories: () => {
        throw new Error('Claude did not answer. Try again.')
      },
    })
    await user.click(await screen.findByRole('button', { name: 'Write a story…' }))
    await user.type(screen.getByLabelText('What did you do?'), 'Something.')
    await user.click(screen.getByRole('button', { name: 'Draft it' }))
    const dialog = within(await screen.findByRole('dialog', { name: 'Write a story' }))
    const alert = await dialog.findByRole('alert')
    expect(alert).toHaveTextContent('Claude did not answer. Try again.')
    expect(alert).toHaveClass('error')
    expect(dialog.getByLabelText('What did you do?')).toHaveValue('Something.')
  })

  it('a bank that could not be read says so in the error box: it is all the part shows', async () => {
    show({
      list_stories: () => {
        throw new Error('Your story bank could not be read.')
      },
    })
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Your story bank could not be read.')
    expect(alert).toHaveClass('error')
  })

  it('a re-read that fails after a save keeps the stories shown and says nothing', async () => {
    const user = userEvent.setup()
    let reads = 0
    show({
      list_stories: () => {
        reads += 1
        if (reads > 1) throw new Error('the server stopped')
        return BANK
      },
    })
    await user.click((await row('Cut build time')).getByRole('button', { name: 'Edit…' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('Saved Cut build time.')).toBeInTheDocument()
    await waitFor(() => expect(reads).toBe(2))
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByRole('listitem', { name: 'Ran the migration' })).toBeInTheDocument()
  })

  it('a removal that failed is said in the error box over the list', async () => {
    const user = userEvent.setup()
    show({
      remove_story: () => {
        throw new Error('Your story could not be removed. Try again.')
      },
    })
    await user.click((await row('Ran the migration')).getByRole('button', { name: 'Remove…' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Your story could not be removed. Try again.')
    expect(alert).toHaveClass('error')
    expect(screen.getByRole('list', { name: 'Your stories' })).toBeInTheDocument()
  })

  it('a draft that failed to save is said in its dialog, which stays', async () => {
    const user = userEvent.setup()
    show({
      draft_stories: { outcome: 'proposed', stories: [story('One')] },
      save_story: () => {
        throw new Error('Your story could not be saved.')
      },
    })
    await user.click(await screen.findByRole('button', { name: 'Write a story…' }))
    await user.type(screen.getByLabelText('What did you do?'), 'One thing.')
    await user.click(screen.getByRole('button', { name: 'Draft it' }))
    const dialog = within(await screen.findByRole('dialog', { name: 'Your story' }))
    await user.click(dialog.getByRole('button', { name: 'Save' }))
    const alert = await dialog.findByRole('alert')
    expect(alert).toHaveTextContent('Your story could not be saved.')
    expect(alert).toHaveClass('error')
    expect(dialog.getByLabelText('Title')).toHaveValue('One')
  })
})
