// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Pair, codeFromHash } from './Pair'

afterEach(cleanup)

function setup(answer: Response | Error, initialCode = '') {
  const fetch = vi.fn(async () => {
    if (answer instanceof Error) throw answer
    return answer
  })
  const onPaired = vi.fn()
  render(<Pair fetch={fetch as unknown as typeof globalThis.fetch} onPaired={onPaired} initialCode={initialCode} />)
  return { fetch, onPaired }
}

describe('Pair', () => {
  it('trades the typed code for a token and hands it on', async () => {
    const { fetch, onPaired } = setup(new Response(JSON.stringify({ device: 'Pixel', token: 't0k' })))
    expect(screen.getByRole('heading', { name: 'Pair this phone' })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Pairing code'), 'abcd-efgh')
    await userEvent.click(screen.getByRole('button', { name: 'Pair' }))
    expect(fetch).toHaveBeenCalledWith('/pair', expect.objectContaining({ method: 'POST', body: JSON.stringify({ code: 'abcd-efgh' }) }))
    expect(onPaired).toHaveBeenCalledWith({ device: 'Pixel', token: 't0k' })
  })

  it("a wrong code says what the server said; nothing is stored", async () => {
    const { onPaired } = setup(new Response(JSON.stringify({ error: 'That code is wrong or has expired.' }), { status: 401 }))
    await userEvent.type(screen.getByLabelText('Pairing code'), 'AAAA-AAAA')
    await userEvent.click(screen.getByRole('button', { name: 'Pair' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That code is wrong or has expired.')
    expect(onPaired).not.toHaveBeenCalled()
  })

  it('no network is said in words', async () => {
    setup(new TypeError('Failed to fetch'))
    await userEvent.type(screen.getByLabelText('Pairing code'), 'AAAA-AAAA')
    await userEvent.click(screen.getByRole('button', { name: 'Pair' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("Can't reach The other door")
  })

  it('a code from the link (the QR code) pairs without typing', async () => {
    const { onPaired } = setup(new Response(JSON.stringify({ device: 'Pixel', token: 't' })), 'WXYZ-2345')
    await vi.waitFor(() => expect(onPaired).toHaveBeenCalled())
  })

  it('says why when it was unpaired', () => {
    render(<Pair fetch={vi.fn() as never} onPaired={vi.fn()} notice="This phone is no longer paired with The other door." />)
    expect(screen.getByText(/This phone is no longer paired with/)).toBeInTheDocument()
  })
})

describe('codeFromHash', () => {
  it('reads #pair=CODE and nothing else', () => {
    expect(codeFromHash('#pair=ABCD-EFGH')).toBe('ABCD-EFGH')
    expect(codeFromHash('#pair=abcd%2Defgh')).toBe('abcd-efgh')
    expect(codeFromHash('')).toBe('')
    expect(codeFromHash('#other=1')).toBe('')
  })
})
