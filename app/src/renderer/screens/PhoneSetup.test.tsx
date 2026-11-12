// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PhoneConnection } from './Connections'
import { PhoneSetup } from './PhoneSetup'
import { mockDoor } from '../testing'

afterEach(cleanup)

const serving = {
  running: true, connection: 'tailscale', address: 'https://mac.tail1234.ts.net', port: 8765, lasting: true,
  devices: [{ device: 'Pixel', paired_at: '2026-10-30T10:00:00+00:00', last_seen: null }], web_built: true, tailscale_installed: true,
}
const idle = { running: false, devices: [], web_built: true, tailscale_installed: false }
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
    await userEvent.click(await row.findByRole('button', { name: 'Set up your phone' }))
    expect(screen.getByRole('dialog', { name: 'Set up your phone' })).toBeInTheDocument()
  })

  it('phones paired but nothing serving, as after a restart: says what to do', async () => {
    connections({ phone_status: { ...idle, devices: [{ device: 'Pixel', paired_at: 'x', last_seen: null }] } })
    const row = within(await screen.findByRole('listitem', { name: 'Your phone' }))
    expect(await row.findByText(/scan a new code/)).toBeInTheDocument()
    expect(row.getByRole('button', { name: 'Set up your phone' })).toBeInTheDocument()
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
    expect(await row.findByRole('button', { name: 'Set up your phone' })).toBeInTheDocument()
    expect(row.queryByRole('alert')).toBeNull()
    expect(call.mock.calls.filter((c) => c[0] === 'phone_status')).toHaveLength(2)
  })

  it('a paired phone: Connected, no names or addresses, and one Disconnect that asks, then unpairs and stops', async () => {
    const { call } = connections({ phone_status: serving, unpair_phone: { removed: 'Pixel' }, phone_stop: { stopped: true } })
    const row = within(await screen.findByRole('listitem', { name: 'Your phone' }))
    expect(await row.findByText('Connected')).toBeInTheDocument()
    expect(row.queryByText(/mac\.tail1234\.ts\.net|Pixel|[Ss]erving/)).toBeNull()
    expect(row.queryByRole('button', { name: 'Pair your phone' })).toBeNull()
    await userEvent.click(row.getByRole('button', { name: 'Disconnect' }))
    const ask = screen.getByRole('dialog', { name: 'Disconnect your phone?' })
    await userEvent.click(within(ask).getByRole('button', { name: 'Cancel' }))
    expect(call.mock.calls.filter((c) => c[0] === 'unpair_phone' || c[0] === 'phone_stop')).toEqual([])
    await userEvent.click(row.getByRole('button', { name: 'Disconnect' }))
    await userEvent.click(within(screen.getByRole('dialog', { name: 'Disconnect your phone?' })).getByRole('button', { name: 'Disconnect' }))
    expect(call.mock.calls.filter((c) => c[0] === 'unpair_phone' || c[0] === 'phone_stop')).toEqual([
      ['unpair_phone', { device: 'Pixel' }],
      ['phone_stop', {}],
    ])
  })

  it('serving, nothing paired yet: Pair your phone opens the QR code', async () => {
    const { call } = connections({ phone_status: { ...serving, devices: [] }, pair_phone: { device: 'My phone', qr_svg: SVG, expires_at: future() } })
    const row = within(await screen.findByRole('listitem', { name: 'Your phone' }))
    await userEvent.click(await row.findByRole('button', { name: 'Pair your phone' }))
    expect(await screen.findByRole('img', { name: 'QR code that pairs your phone' })).toBeInTheDocument()
    expect(call.mock.calls.filter((c) => c[0] === 'pair_phone')).toEqual([['pair_phone', { device: 'My phone' }]])
  })
})

describe('PhoneSetup', () => {
  it('nothing to choose or install: Continue, the QR code, then the home screen', async () => {
    let paired = false
    const started = { ...serving, connection: 'cloudflare', lasting: false, address: 'https://x.trycloudflare.com' }
    const { call } = mockDoor({
      phone_start: started,
      pair_phone: () => ({ device: 'My phone', qr_svg: SVG, expires_at: future() }),
      phone_status: () => (paired ? { ...started, devices: [...started.devices, { device: 'My phone', paired_at: 'x', last_seen: null }] } : started),
    })
    render(<PhoneSetup onClose={vi.fn()} pollMs={5} />)
    expect(screen.getByText(/passes through Cloudflare/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(call).toHaveBeenCalledWith('phone_start', { connection: 'cloudflare' })
    expect(await screen.findByText(/changes when this computer restarts/)).toBeInTheDocument()

    // the QR code at once, and nothing to read or type
    const qr = await screen.findByRole('img', { name: 'QR code that pairs your phone' })
    expect(call).toHaveBeenCalledWith('pair_phone', { device: 'My phone' })
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(qr.getAttribute('src')).toMatch(/^data:image\/svg\+xml;base64,/)
    expect(screen.queryByText(/#pair=/)).toBeNull()

    paired = true // the phone scanned it
    expect(await screen.findByRole('heading', { name: 'Add The other door to your home screen' })).toBeInTheDocument()
    expect(screen.getByText(/Install app/)).toBeInTheDocument()
    expect(screen.getByText(/Add to Home Screen/)).toBeInTheDocument()
  })

  it('a phone paired before, scanning again under its name, counts as paired once its date changes', async () => {
    const before = { device: 'My phone', paired_at: '2026-10-30T10:00:00+00:00', last_seen: null }
    let rescanned = false
    mockDoor({
      phone_start: { ...serving, connection: 'cloudflare', lasting: false, devices: [before] },
      pair_phone: { device: 'My phone', qr_svg: SVG, expires_at: future() },
      phone_status: () => ({ ...serving, devices: [rescanned ? { ...before, paired_at: '2026-10-31T10:00:00+00:00' } : before] }),
    })
    render(<PhoneSetup onClose={vi.fn()} pollMs={5} />)
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await screen.findByRole('img', { name: 'QR code that pairs your phone' })
    await new Promise((r) => setTimeout(r, 30))
    expect(screen.queryByRole('heading', { name: 'Add The other door to your home screen' })).toBeNull()
    rescanned = true
    expect(await screen.findByRole('heading', { name: 'Add The other door to your home screen' })).toBeInTheDocument()
    expect(screen.getByText(/add it again/)).toBeInTheDocument()
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
