// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StatusDialog } from './StatusDialog'
import { Matches } from './Matches'
import { match, matchesResult, mockDoor, summary } from '../testing'

afterEach(cleanup)

describe('StatusDialog preset to discarded', () => {
  it('records the reason as a note and tells the caller', async () => {
    const { call } = mockDoor({ set_status: { status: 'discarded' } })
    const onDone = vi.fn()
    render(<StatusDialog jobId="jobindex.1" title="Analyst" current="unapplied" preset="discarded" onClose={() => {}} onDone={onDone} />)
    await userEvent.type(screen.getByLabelText('Why not?'), 'too far')
    await userEvent.click(screen.getByRole('button', { name: 'Discard' }))
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(call).toHaveBeenCalledWith('set_status', { job_id: 'jobindex.1', status: 'discarded', notes: 'too far' })
  })

  it('cancel closes without a call', async () => {
    const { call } = mockDoor({})
    const onClose = vi.fn()
    render(<StatusDialog jobId="jobindex.1" title="Analyst" current="unapplied" preset="discarded" onClose={onClose} onDone={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onClose).toHaveBeenCalled()
    expect(call).not.toHaveBeenCalled()
  })

  it('cannot be confirmed while the reason is empty', async () => {
    mockDoor({})
    render(<StatusDialog jobId="jobindex.1" title="Analyst" current="unapplied" preset="discarded" onClose={() => {}} onDone={() => {}} />)
    const confirm = screen.getByRole('button', { name: 'Discard' })
    expect(confirm).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Why not?'), '   ')
    expect(confirm).toBeDisabled()
  })

  it('stays open and shows the {error} when the server refuses', async () => {
    mockDoor({
      set_status: () => {
        throw { message: 'a run is in progress' }
      },
    })
    const onDone = vi.fn()
    render(<StatusDialog jobId="jobindex.1" title="Analyst" current="unapplied" preset="discarded" onClose={() => {}} onDone={onDone} />)
    await userEvent.type(screen.getByLabelText('Why not?'), 'too far')
    await userEvent.click(screen.getByRole('button', { name: 'Discard' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('a run is in progress')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(onDone).not.toHaveBeenCalled()
  })

  it('closes on Escape and keeps Tab inside', async () => {
    mockDoor({})
    const onClose = vi.fn()
    render(<StatusDialog jobId="jobindex.1" title="Analyst" current="unapplied" preset="discarded" onClose={onClose} onDone={() => {}} />)
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByLabelText('Why not?')).toHaveFocus()
    await userEvent.tab()
    await userEvent.tab()
    await userEvent.tab()
    expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true)
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })
})


const open = (over: Record<string, unknown> = {}) => {
  const onDone = vi.fn()
  const onClose = vi.fn()
  render(<StatusDialog jobId="jobindex.1" title="Analyst" current="unapplied" onClose={onClose} onDone={onDone} {...over} />)
  return { onDone, onClose }
}
const save = () => userEvent.click(screen.getByRole('button', { name: 'Save' }))

describe('StatusDialog', () => {
  it('lists the eight statuses in words with the current one chosen', () => {
    mockDoor({})
    open({ current: 'applied' })
    const words = ['Not yet applied', 'Prepared', 'Applied', 'Interview', 'Ghosted', 'Rejected', 'Offer', 'Not for me']
    for (const w of words) expect(screen.getByRole('radio', { name: w })).toBeInTheDocument()
    expect(screen.getAllByRole('radio', { name: /^(Not yet applied|Prepared|Applied|Interview|Ghosted|Rejected|Offer|Not for me)$/ })).toHaveLength(8)
    expect(screen.getByRole('radio', { name: 'Applied' })).toBeChecked()
  })

  it('starts with the focus on the current status, not the first one', () => {
    mockDoor({})
    render(<StatusDialog jobId="jobindex.1" title="Analyst" current="interview:screening" onClose={() => {}} onDone={() => {}} />)
    expect(screen.getByRole('radio', { name: 'Interview' })).toHaveFocus()
  })

  it('starts on the first status when none is current', () => {
    mockDoor({})
    render(<StatusDialog jobId="jobindex.1" title="Analyst" current="" onClose={() => {}} onDone={() => {}} />)
    expect(screen.getByRole('radio', { name: 'Not yet applied' })).toHaveFocus()
  })

  it('Interview reveals the four kinds with their meanings; Save waits for one', async () => {
    const { call } = mockDoor({ set_status: { status: 'interview:technical' } })
    const { onDone } = open({ current: 'applied' })
    expect(screen.queryByRole('radio', { name: /Screening/ })).toBeNull()
    await userEvent.click(screen.getByRole('radio', { name: 'Interview' }))
    for (const k of ['Screening', 'First impression', 'Assessment', 'Technical']) {
      expect(screen.getByRole('radio', { name: new RegExp(k) })).not.toBeChecked()
    }
    expect(screen.getByText(/technical interview, case or take-home/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    await userEvent.click(screen.getByRole('radio', { name: /Technical/ }))
    await save()
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(call).toHaveBeenCalledWith('set_status', { job_id: 'jobindex.1', status: 'interview:technical' })
  })

  it('a discard needs a reason and sends it as notes', async () => {
    const { call } = mockDoor({ set_status: { status: 'discarded' } })
    open({ current: 'prepared' })
    await userEvent.click(screen.getByRole('radio', { name: 'Not for me' }))
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Why not?'), ' too far ')
    await save()
    await waitFor(() => expect(call).toHaveBeenCalled())
    expect(call).toHaveBeenCalledWith('set_status', { job_id: 'jobindex.1', status: 'discarded', notes: 'too far' })
  })

  it('sends optional notes only when there are some', async () => {
    const { call } = mockDoor({ set_status: { status: 'rejected' } })
    open({ current: 'applied' })
    await userEvent.click(screen.getByRole('radio', { name: 'Rejected' }))
    await save()
    await waitFor(() => expect(call).toHaveBeenCalledTimes(1))
    expect(call).toHaveBeenLastCalledWith('set_status', { job_id: 'jobindex.1', status: 'rejected' })
    cleanup()
    const again = mockDoor({ set_status: { status: 'rejected' } })
    open({ current: 'applied' })
    await userEvent.click(screen.getByRole('radio', { name: 'Rejected' }))
    await userEvent.type(screen.getByLabelText(/Notes/), 'no feedback')
    await save()
    await waitFor(() => expect(again.call).toHaveBeenCalled())
    expect(again.call).toHaveBeenCalledWith('set_status', { job_id: 'jobindex.1', status: 'rejected', notes: 'no feedback' })
  })

  it('shows the server error as an alert and stays open', async () => {
    mockDoor({
      set_status: () => {
        throw { message: 'a run is in progress' }
      },
    })
    const { onDone } = open({ current: 'unapplied' })
    await userEvent.click(screen.getByRole('radio', { name: 'Prepared' }))
    await save()
    expect(await screen.findByRole('alert')).toHaveTextContent('a run is in progress')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(onDone).not.toHaveBeenCalled()
  })

  it('hands the result to onDone', async () => {
    mockDoor({ set_status: { job_id: 'jobindex.1', status: 'applied', current: 'applied', warning: 'short ad' } })
    const { onDone } = open({ current: 'unapplied' })
    await userEvent.click(screen.getByRole('radio', { name: 'Applied' }))
    await save()
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(expect.objectContaining({ status: 'applied', warning: 'short ad' })))
  })

  it('shows no id, path or raw interview status', async () => {
    mockDoor({})
    const { container } = render(<StatusDialog jobId="jobindex.1" title="Analyst" current="interview:screening" onClose={() => {}} onDone={() => {}} />)
    await userEvent.click(screen.getByRole('radio', { name: 'Interview' }))
    expect(container.textContent).not.toMatch(/jobindex\.1|interview:|\//)
  })
})

describe('discarding from the Matches screen', () => {
  it('removes the job from the list after the reason is saved', async () => {
    let discarded = false
    const rows = [match({ id: 'jobindex.1', title: 'Keep me' }), match({ id: 'jobindex.2', title: 'Drop me' })]
    const { call } = mockDoor({
      status_summary: summary(),
      list_matches: () => matchesResult(discarded ? rows.slice(0, 1) : rows),
      show: (args: Record<string, unknown>) => ({ ...rows.find((r) => r.id === args.job_id), description: 'd', url: '' }),
      set_status: () => {
        discarded = true
        return { status: 'discarded' }
      },
    })
    render(<Matches />)
    await userEvent.click(await screen.findByRole('button', { name: /Drop me/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Not for me' }))
    await userEvent.type(screen.getByLabelText('Why not?'), 'too far')
    await userEvent.click(screen.getByRole('button', { name: 'Discard' }))
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Drop me', level: 2 })).toBeNull())
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(call).toHaveBeenCalledWith('set_status', { job_id: 'jobindex.2', status: 'discarded', notes: 'too far' })
    expect((await screen.findAllByText('Keep me')).length).toBeGreaterThan(0)
  })
})
