// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../../testing'
import { Connect } from './Connect'
import { doctorReport } from './testing'

afterEach(cleanup)

const missing = { ok: false, checks: [{ name: 'claude CLI', status: 'missing', required: true, detail: '' }] }

describe('Connect', () => {
  it('signed out: offers the sign-in, and can check again', async () => {
    mockDoor({})
    const onRecheck = vi.fn()
    render(<Connect doctor={doctorReport('out')} onRecheck={onRecheck} />)
    expect(screen.getByRole('button', { name: 'Sign in with Claude' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Check again' }))
    expect(onRecheck).toHaveBeenCalled()
  })

  it('a missing Claude installs after one yes, then checks again', async () => {
    const { call } = mockDoor({ setup: { outcome: 'ok' } })
    const onRecheck = vi.fn()
    render(<Connect doctor={missing} onRecheck={onRecheck} />)
    await userEvent.click(screen.getByRole('button', { name: 'Install Claude' }))
    expect(call).not.toHaveBeenCalledWith('setup', expect.anything())
    await userEvent.click(screen.getByRole('button', { name: 'Install' }))
    await waitFor(() => expect(onRecheck).toHaveBeenCalled())
    expect(call).toHaveBeenCalledWith('setup', { install: ['claude'], yes: true })
  })

  it('Cancel or Escape on the install question installs nothing', async () => {
    const { call } = mockDoor({ setup: { outcome: 'ok' } })
    render(<Connect doctor={missing} onRecheck={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Install Claude' }))
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Install Claude' }))
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(call).not.toHaveBeenCalledWith('setup', expect.anything())
  })

  it('stays busy until the check after the install has answered', async () => {
    mockDoor({ setup: { outcome: 'ok' } })
    let answer = () => {}
    const onRecheck = vi.fn(() => new Promise<void>((resolve) => (answer = resolve)))
    render(<Connect doctor={missing} onRecheck={onRecheck} />)
    await userEvent.click(screen.getByRole('button', { name: 'Install Claude' }))
    await userEvent.click(screen.getByRole('button', { name: 'Install' }))
    await waitFor(() => expect(onRecheck).toHaveBeenCalled())
    expect(screen.getByRole('button', { name: 'Install Claude' })).toBeDisabled()
    expect(screen.getByText('Installing…')).toBeInTheDocument()
    answer()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Install Claude' })).toBeEnabled())
  })

  it('says why from the install step alone, not the other setup to-dos', async () => {
    mockDoor({ setup: { outcome: 'incomplete', results: [{ tool: 'claude', ok: false, error: 'Unable to locate package' }], todo: ['create your profile'] } })
    const onRecheck = vi.fn()
    render(<Connect doctor={missing} onRecheck={onRecheck} />)
    await userEvent.click(screen.getByRole('button', { name: 'Install Claude' }))
    await userEvent.click(screen.getByRole('button', { name: 'Install' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to locate package')
    expect(screen.getByRole('button', { name: 'Install Claude' })).toBeEnabled()
    // installed by hand: no need to restart to be seen
    await userEvent.click(screen.getByRole('button', { name: 'Check again' }))
    await waitFor(() => expect(onRecheck).toHaveBeenCalledTimes(2))
  })

  it('has words of its own when a failed install leaves none', async () => {
    mockDoor({ setup: { outcome: 'incomplete', results: [{ tool: 'claude', ok: false }] } })
    render(<Connect doctor={missing} onRecheck={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Install Claude' }))
    await userEvent.click(screen.getByRole('button', { name: 'Install' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The install did not finish.')
  })

  it('says so when an install reports success but Claude is still not found', async () => {
    mockDoor({ setup: { outcome: 'incomplete', results: [{ tool: 'claude', ok: true }], todo: ['create your profile'] } })
    render(<Connect doctor={missing} onRecheck={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Install Claude' }))
    await userEvent.click(screen.getByRole('button', { name: 'Install' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/still can.t be found/)
  })

  it('says why an install failed and stays; installed by hand, Check again asks again', async () => {
    const onRecheck = vi.fn()
    mockDoor({ setup: () => { throw new Error('no network') } })
    render(<Connect doctor={missing} onRecheck={onRecheck} />)
    await userEvent.click(screen.getByRole('button', { name: 'Install Claude' }))
    await userEvent.click(screen.getByRole('button', { name: 'Install' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('no network')
    expect(screen.getByRole('button', { name: 'Install Claude' })).toBeEnabled()
    onRecheck.mockClear()
    await userEvent.click(screen.getByRole('button', { name: 'Check again' }))
    expect(onRecheck).toHaveBeenCalledTimes(1)
  })
})
