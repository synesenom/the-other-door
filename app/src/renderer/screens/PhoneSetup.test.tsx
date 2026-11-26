// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PhoneConnection } from './Connections'
import { PhoneSetup } from './PhoneSetup'
import { mockDoor } from '../testing'

afterEach(cleanup)

const serving = {
  running: true, address: 'https://x.trycloudflare.com', port: 8765,
  devices: [{ device: 'Pixel', paired_at: '2026-10-30T10:00:00+00:00', last_seen: null }], web_built: true,
}
const idle = { running: false, devices: [], web_built: true }
const SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'
const future = () => new Date(Date.now() + 5 * 60_000).toISOString()

function connections(handlers: Record<string, unknown>) {
  const h = mockDoor(handlers)
  render(<ul><PhoneConnection /></ul>)
  return h
}

describe('Connections: Your phone', () => {
  it('not set up: only the setup', async () => {
    connections({ phone_status: idle })
    const row = within(await screen.findByRole('listitem', { name: 'Your phone' }))
    await userEvent.click(await row.findByRole('button', { name: 'Set up your phone…' }))
    expect(screen.getByRole('dialog', { name: 'Set up your phone' })).toBeInTheDocument()
  })

  it('a phone left paired, nothing serving (after a restart): set it up again (starting forgets the old pairing)', async () => {
    connections({ phone_status: { ...idle, devices: [{ device: 'Pixel', paired_at: 'x', last_seen: null }] } })
    const row = within(await screen.findByRole('listitem', { name: 'Your phone' }))
    expect(await row.findByRole('button', { name: 'Set up your phone…' })).toBeInTheDocument()
    expect(row.queryByRole('button', { name: 'Disconnect…' })).toBeNull()
  })

  it('the state cannot be read: says why, and Check again reads it again', async () => {
    let fails = true
    const { call } = connections({
      phone_status: () => {
        if (fails) throw new Error('the phone server state is unreadable')
        return idle
      },
    })
    const row = within(await screen.findByRole('listitem', { name: 'Your phone' }))
    expect(await row.findByRole('alert')).toHaveTextContent('the phone server state is unreadable')
    fails = false
    await userEvent.click(row.getByRole('button', { name: 'Check again' }))
    expect(await row.findByRole('button', { name: 'Set up your phone…' })).toBeInTheDocument()
    expect(row.queryByRole('alert')).toBeNull()
    expect(call.mock.calls.filter((c) => c[0] === 'phone_status')).toHaveLength(2)
  })

  it('a paired phone: Connected, no names or addresses, and one Disconnect that asks, then stops (the pairing ends with it)', async () => {
    const { call } = connections({ phone_status: serving, phone_stop: { stopped: true } })
    const row = within(await screen.findByRole('listitem', { name: 'Your phone' }))
    expect(await row.findByText('Connected until this computer restarts')).toBeInTheDocument()
    expect(row.queryByText(/trycloudflare|Pixel|[Ss]erving/)).toBeNull()
    expect(row.queryByRole('button', { name: 'Pair your phone…' })).toBeNull()
    await userEvent.click(row.getByRole('button', { name: 'Disconnect…' }))
    const ask = screen.getByRole('dialog', { name: 'Disconnect your phone?' })
    await userEvent.click(within(ask).getByRole('button', { name: 'Cancel' }))
    expect(call.mock.calls.filter((c) => c[0] === 'unpair_phone' || c[0] === 'phone_stop')).toEqual([])
    await userEvent.click(row.getByRole('button', { name: 'Disconnect…' }))
    await userEvent.click(within(screen.getByRole('dialog', { name: 'Disconnect your phone?' })).getByRole('button', { name: 'Disconnect' }))
    expect(call.mock.calls.filter((c) => c[0] === 'unpair_phone' || c[0] === 'phone_stop')).toEqual([['phone_stop', {}]])
  })

  it('serving, nothing paired yet: Pair your phone opens the QR code', async () => {
    const { call } = connections({ phone_status: { ...serving, devices: [] }, pair_phone: { device: 'My phone', qr_svg: SVG, expires_at: future() } })
    const row = within(await screen.findByRole('listitem', { name: 'Your phone' }))
    await userEvent.click(await row.findByRole('button', { name: 'Pair your phone…' }))
    expect(await screen.findByRole('img', { name: 'QR code that pairs your phone' })).toBeInTheDocument()
    expect(call.mock.calls.filter((c) => c[0] === 'pair_phone')).toEqual([['pair_phone', { device: 'My phone' }]])
  })
})

describe('PhoneSetup', () => {
  it('nothing to choose or install: Continue, the QR code, then the home screen', async () => {
    let paired = false
    const started = { ...serving, devices: [] }
    const { call } = mockDoor({
      phone_start: started,
      pair_phone: () => ({ device: 'My phone', qr_svg: SVG, expires_at: future() }),
      phone_status: () => (paired ? { ...started, devices: [{ device: 'My phone', paired_at: 'x', last_seen: null }] } : started),
    })
    render(<PhoneSetup onClose={vi.fn()} pollMs={5} />)
    expect(screen.getByText(/passes through Cloudflare/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(call).toHaveBeenCalledWith('phone_start', {})
    expect(await screen.findByText(/changes when this computer restarts/)).toBeInTheDocument()

    // the QR code at once, and nothing to read or type
    const qr = await screen.findByRole('img', { name: 'QR code that pairs your phone' })
    expect(call).toHaveBeenCalledWith('pair_phone', { device: 'My phone' })
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(qr.getAttribute('src')).toMatch(/^data:image\/svg\+xml;base64,/)
    expect(screen.queryByText(/#pair=/)).toBeNull()

    paired = true // the phone scanned it
    expect(await screen.findByRole('heading', { name: 'Add The other door to your home screen' })).toBeInTheDocument()
    expect(screen.getByText(/it offers to install it as an app/)).toBeInTheDocument()
  })


  it('the address is asked for as the dialog opens: Continue waits for it, saying so', async () => {
    let ready: (v: unknown) => void = () => undefined
    const { call } = mockDoor({
      phone_start: () => new Promise((r) => (ready = r)),
      pair_phone: () => ({ device: 'My phone', qr_svg: SVG, expires_at: future() }),
      phone_status: { ...serving, devices: [] },
    })
    render(<PhoneSetup onClose={vi.fn()} pollMs={5} />)
    expect(call.mock.calls.filter((c) => c[0] === 'phone_start')).toEqual([['phone_start', {}]])
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByText(/Getting your phone's address/)).toBeInTheDocument()
    ready({ ...serving, devices: [] })
    expect(await screen.findByRole('img', { name: 'QR code that pairs your phone' })).toBeInTheDocument()
    expect(call.mock.calls.filter((c) => c[0] === 'phone_start')).toHaveLength(1)
  })

  it('Cancel before Continue stops what opening started', async () => {
    const onClose = vi.fn()
    const { call } = mockDoor({ phone_start: { ...serving, devices: [] }, phone_stop: { stopped: true } })
    render(<PhoneSetup onClose={onClose} pollMs={5} />)
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await vi.waitFor(() => expect(call).toHaveBeenCalledWith('phone_stop', {}))
    expect(onClose).toHaveBeenCalled()
  })

  it('a start that failed is tried again by Continue', async () => {
    let n = 0
    const { call } = mockDoor({
      phone_start: () => (n++ === 0 ? { error: 'the tunnel could not connect to Cloudflare' } : { ...serving, devices: [] }),
      pair_phone: () => ({ device: 'My phone', qr_svg: SVG, expires_at: future() }),
      phone_status: { ...serving, devices: [] },
    })
    render(<PhoneSetup onClose={vi.fn()} pollMs={5} />)
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByText('the tunnel could not connect to Cloudflare')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByRole('img', { name: 'QR code that pairs your phone' })).toBeInTheDocument()
    expect(call.mock.calls.filter((c) => c[0] === 'phone_start')).toHaveLength(2)
  })

  it('an expired code says so and makes a new one on a click', async () => {
    let n = 0
    const { call } = mockDoor({
      phone_start: serving,
      phone_status: serving,
      pair_phone: () => ({ device: 'My phone', qr_svg: SVG, expires_at: n++ === 0 ? new Date(Date.now() - 1000).toISOString() : future() }),
    })
    render(<PhoneSetup onClose={vi.fn()} pollMs={5} start="pair" />)
    expect(await screen.findByText(/This code has expired/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'New code' }))
    expect(call.mock.calls.filter((c) => c[0] === 'pair_phone')).toHaveLength(2)
    expect(await screen.findByRole('img', { name: 'QR code that pairs your phone' })).toBeInTheDocument()
  })

  it('a code that could not be made says why, and Try again makes one', async () => {
    let fails = true
    const { call } = mockDoor({
      phone_status: serving,
      pair_phone: () => (fails ? { error: 'The other door is not serving a phone yet; start it first' } : { device: 'My phone', qr_svg: SVG, expires_at: future() }),
    })
    render(<PhoneSetup onClose={vi.fn()} pollMs={5} start="pair" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('not serving a phone yet')
    fails = false
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('img', { name: 'QR code that pairs your phone' })).toBeInTheDocument()
    expect(call.mock.calls.filter((c) => c[0] === 'pair_phone')).toHaveLength(2)
  })

  it('an error is said in words', async () => {
    mockDoor({ phone_start: { error: 'door serve did not start; see logs/serve.log' } })
    render(<PhoneSetup onClose={vi.fn()} pollMs={5} />)
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('door serve did not start')
  })
})

describe('PhoneSetup: leaving', () => {
  const pairing = () => {
    const onClose = vi.fn()
    mockDoor({ phone_status: serving, pair_phone: { device: 'My phone', qr_svg: SVG, expires_at: future() } })
    render(<PhoneSetup onClose={onClose} start="pair" />)
    return onClose
  }

  it('can be closed while the code is made and while it shows', async () => {
    const onClose = pairing()
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(1)
    await screen.findByRole('img', { name: 'QR code that pairs your phone' })
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(2)
  })

  it('Escape still works after the button that had the focus went away', async () => {
    const onClose = pairing()
    await screen.findByRole('img', { name: 'QR code that pairs your phone' })
    expect(document.activeElement).not.toBe(document.body)
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })
})
