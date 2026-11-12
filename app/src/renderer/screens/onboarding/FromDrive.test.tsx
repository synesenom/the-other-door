// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../../testing'
import { FromDrive } from './FromDrive'

afterEach(cleanup)

const ask = () => screen.getByRole('button', { name: 'Bring my profile from Google Drive' })

function setup(handlers: Record<string, unknown>) {
  const h = mockDoor(handlers as never)
  const onPulled = vi.fn()
  render(<FromDrive onPulled={onPulled} />)
  return { ...h, onPulled }
}
const tools = (h: { call: { mock: { calls: unknown[][] } } }) => h.call.mock.calls.map((c) => c[0])

describe('FromDrive', () => {
  it('connects, pulls what is on Drive and hands over, with nothing else called', async () => {
    const h = setup({ connect_drive: { account: 'ada@example.com' }, sync_data: { action: 'pull' } })
    await userEvent.click(ask())
    await waitFor(() => expect(h.onPulled).toHaveBeenCalledTimes(1))
    expect(tools(h)).toEqual(['connect_drive', 'sync_data'])
  })

  it('says so when Drive has nothing yet, and leaves the wizard to go on', async () => {
    const h = setup({ connect_drive: { account: 'ada@example.com' }, sync_data: { action: 'nothing' } })
    await userEvent.click(ask())
    expect(await screen.findByRole('status')).toHaveTextContent('There is nothing from The other door on your Google Drive yet')
    expect(h.onPulled).not.toHaveBeenCalled()
    expect(ask()).toBeEnabled() // it can be tried again
  })

  it('says why when the sign-in is refused or Drive is not configured', async () => {
    const h = setup({
      connect_drive: () => {
        throw new Error('Google Drive sync is not configured in this build.')
      },
    })
    await userEvent.click(ask())
    expect(await screen.findByRole('alert')).toHaveTextContent('not configured in this build')
    expect(tools(h)).toEqual(['connect_drive'])
    expect(h.onPulled).not.toHaveBeenCalled()
  })

  it('says why when the pull fails', async () => {
    const h = setup({
      connect_drive: { account: 'a' },
      sync_data: () => {
        throw new Error('Google Drive is not reachable.')
      },
    })
    await userEvent.click(ask())
    expect(await screen.findByRole('alert')).toHaveTextContent('not reachable')
    expect(h.onPulled).not.toHaveBeenCalled()
  })

  it('waits for the browser: the button is busy meanwhile', async () => {
    let finish: (v: unknown) => void = () => undefined
    setup({ connect_drive: () => new Promise((r) => (finish = r)), sync_data: { action: 'pull' } })
    await userEvent.click(ask())
    expect(await screen.findByRole('status')).toHaveTextContent('Finish signing in to Google in your browser')
    expect(ask()).toBeDisabled()
    finish({ account: 'a' })
  })
})
