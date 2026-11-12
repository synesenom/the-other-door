// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../testing'
import { Ask } from './Ask'

afterEach(cleanup)

function show(handlers: Record<string, unknown>) {
  const h = mockDoor(handlers)
  const onGo = vi.fn()
  render(<Ask onGo={onGo} />)
  return { ...h, onGo }
}

const field = () => screen.getByLabelText('Ask about your jobs')

describe('Ask', () => {
  it('sends the question on Enter and shows the answer in words, with where it came from', async () => {
    const { call } = show({ ask: { answer: 'You applied to 2 jobs in September.', go_to: null, sources: ['query_jobs', 'status_summary'] } })
    await userEvent.type(field(), 'How many in September?{Enter}')
    expect(call).toHaveBeenCalledWith('ask', { question: 'How many in September?' })
    expect(await screen.findByText('You applied to 2 jobs in September.')).toBeInTheDocument()
    expect(screen.getByText('from: query_jobs, status_summary')).toBeInTheDocument()
  })

  it('a screen that shows the answer is one click away', async () => {
    const { onGo } = show({ ask: { answer: 'Two interviews.', go_to: { screen: 'applications', job_ids: ['a', 'b'] }, sources: [] } })
    await userEvent.type(field(), 'my interviews?{Enter}')
    await userEvent.click(await screen.findByRole('button', { name: 'Open Applications' }))
    expect(onGo).toHaveBeenCalledWith({ screen: 'applications', job_ids: ['a', 'b'] })
  })

  it('one job is opened by name', async () => {
    const { onGo } = show({ ask: { answer: 'Data Analyst at Acme.', go_to: { screen: 'posting', job_ids: ['jobindex.1'] }, sources: [] } })
    await userEvent.type(field(), 'which?{Enter}')
    await userEvent.click(await screen.findByRole('button', { name: 'Open the posting' }))
    expect(onGo).toHaveBeenCalledWith({ screen: 'posting', job_ids: ['jobindex.1'] })
  })

  it('a failure is said in words', async () => {
    show({
      ask: () => {
        throw { message: 'the answer timed out after 180 s' }
      },
    })
    await userEvent.type(field(), 'q{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('timed out')
  })

  it('while it looks, a second question waits: the field and the button are off', async () => {
    let answer: (v: unknown) => void = () => {}
    show({ ask: () => new Promise((r) => (answer = r)) })
    await userEvent.type(field(), 'first{Enter}')
    expect(screen.getByRole('status')).toHaveTextContent('Looking')
    expect(field()).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled()
    answer({ answer: 'done', go_to: null, sources: [] })
    expect(await screen.findByText('done')).toBeInTheDocument()
    expect(field()).toBeEnabled()
  })

  it('an empty question is not sent, and the up arrow brings back the last one', async () => {
    const { call } = show({ ask: { answer: 'ok', go_to: null, sources: [] } })
    await userEvent.type(field(), '   {Enter}')
    expect(call).not.toHaveBeenCalled()
    await userEvent.type(field(), 'how many?{Enter}')
    await screen.findByText('ok')
    await userEvent.clear(field())
    await userEvent.type(field(), '{ArrowUp}')
    expect(field()).toHaveValue('how many?')
    await userEvent.type(field(), '{ArrowDown}')
    expect(field()).toHaveValue('')
  })
})
