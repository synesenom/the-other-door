// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../renderer/App', () => ({ App: () => <h1>The desktop screens</h1> }))

import { Web } from './Web'
import { captureInstallPrompt } from './install'
import type { TokenStore } from './token-store'

beforeEach(() => {
  localStorage.clear()
  window.matchMedia = vi.fn().mockReturnValue({ matches: false }) as never
})

afterEach(() => {
  cleanup()
  window.dispatchEvent(new Event('appinstalled')) // forgets a kept install prompt
  window.location.hash = ''
  window.history.replaceState(null, '', '/')
})

function memoryStore(initial: string | null = null): TokenStore & { value: string | null } {
  const s = {
    value: initial,
    async get() {
      return s.value
    },
    async set(t: string) {
      s.value = t
    },
    async clear() {
      s.value = null
    },
  }
  return s
}

function server(routes: Record<string, () => Response>) {
  return vi.fn(async (url: string) => (routes[url] ?? (() => new Response('{}')))())
}

describe('Web', () => {
  it('unpaired: the pair screen; a good code stores the token, opens the files session and shows the app', async () => {
    const store = memoryStore()
    const fetch = server({ '/pair': () => new Response(JSON.stringify({ device: 'Pixel', token: 'tok' })) })
    render(<Web store={store} fetch={fetch as never} />)
    await userEvent.type(await screen.findByLabelText('Pairing code'), 'ABCD-EFGH')
    await userEvent.click(screen.getByRole('button', { name: 'Pair' }))
    expect(await screen.findByRole('heading', { name: 'The desktop screens' })).toBeInTheDocument()
    expect(store.value).toBe('tok')
    expect(fetch).toHaveBeenCalledWith('/session', expect.objectContaining({ method: 'POST', headers: { Authorization: 'Bearer tok' } }))
    expect(window.door.invoke).toBeDefined()
  })

  it('shows the splash while it reads the pairing', async () => {
    const store = { ...memoryStore(), get: () => new Promise<string | null>(() => undefined) }
    render(<Web store={store} fetch={server({}) as never} />)
    expect(screen.getByRole('status', { name: 'Starting The other door' })).toBeInTheDocument()
  })

  it('paired: straight to the app', async () => {
    render(<Web store={memoryStore('tok')} fetch={server({}) as never} />)
    expect(await screen.findByRole('heading', { name: 'The desktop screens' })).toBeInTheDocument()
  })

  it('a revoked token: back to the pair screen, saying why, with the token gone', async () => {
    const store = memoryStore('old')
    render(<Web store={store} fetch={server({ '/session': () => new Response('{}', { status: 401 }) }) as never} />)
    expect(await screen.findByText(/no longer paired/)).toBeInTheDocument()
    expect(store.value).toBeNull()
  })

  it('unpaired while in use (a 401 from a call): the pair screen again', async () => {
    const store = memoryStore('tok')
    const fetch = server({ '/mcp': () => new Response('{}', { status: 401 }) })
    render(<Web store={store} fetch={fetch as never} />)
    await screen.findByRole('heading', { name: 'The desktop screens' })
    await act(async () => {
      await window.door.call('list_matches')
    })
    expect(await screen.findByRole('heading', { name: 'Pair this phone' })).toBeInTheDocument()
    expect(store.value).toBeNull()
  })

  it('an already paired phone ignores a code left in the link (a reopened tab, a used code)', async () => {
    window.location.hash = '#pair=USED-CODE'
    const fetch = server({ '/pair': () => new Response(JSON.stringify({ error: 'That code is wrong or has expired.' }), { status: 401 }) })
    render(<Web store={memoryStore('tok')} fetch={fetch as never} />)
    expect(await screen.findByRole('heading', { name: 'The desktop screens' })).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalledWith('/pair', expect.anything())
    expect(window.location.hash).toBe('')
  })

  it("a code in the link pairs without typing, and leaves the address", async () => {
    window.location.hash = '#pair=WXYZ-2345'
    const store = memoryStore()
    render(<Web store={store} fetch={server({ '/pair': () => new Response(JSON.stringify({ device: 'P', token: 't' })) }) as never} />)
    expect(await screen.findByRole('heading', { name: 'The desktop screens' })).toBeInTheDocument()
    expect(window.location.hash).toBe('')
  })

  it('a shared link is imported and scored, then its posting opens; the address goes back to /', async () => {
    window.history.pushState(null, '', '/share?text=' + encodeURIComponent('A job https://jobs.example.com/9'))
    const calls: unknown[] = []
    const fetch = vi.fn(async (url: string, init?: RequestInit) => {
      if (url !== '/mcp') return new Response('{}')
      const body = JSON.parse(String(init?.body))
      calls.push(body.params)
      const value = body.params.name === 'import_posting' ? { job_id: 'manual.9', score: 0.7 } : {}
      return new Response(JSON.stringify({ jsonrpc: '2.0', id: 1, result: { content: [{ type: 'text', text: JSON.stringify(value) }] } }))
    })
    render(<Web store={memoryStore('tok')} fetch={fetch as never} />)
    expect(await screen.findByRole('heading', { name: 'The desktop screens' })).toBeInTheDocument()
    expect(calls).toContainEqual({ name: 'import_posting', arguments: { url: 'https://jobs.example.com/9' } })
    const seen: unknown[] = []
    window.door.on('open', (t) => seen.push(t))
    expect(seen).toEqual([{ screen: 'posting', jobId: 'manual.9', inPlay: false }])
    expect(window.location.pathname).toBe('/')
  })

  it('a share that cannot be imported says why, with a way on to the app', async () => {
    window.history.pushState(null, '', '/share?url=' + encodeURIComponent('https://jobs.example.com/x'))
    const fetch = vi.fn(async (url: string) =>
      url === '/mcp'
        ? new Response(JSON.stringify({ jsonrpc: '2.0', id: 1, result: { content: [{ type: 'text', text: JSON.stringify({ error: 'The page could not be read.' }) }] } }))
        : new Response('{}'),
    )
    render(<Web store={memoryStore('tok')} fetch={fetch as never} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('The page could not be read.')
    await userEvent.click(screen.getByRole('button', { name: 'Go to The other door' }))
    expect(await screen.findByRole('heading', { name: 'The desktop screens' })).toBeInTheDocument()
  })

  it("a computer that cannot be reached: our own screen, not the tunnel's error; Try again opens the app once it answers", async () => {
    let down = true
    const fetch = vi.fn(async (url: string) => (url === '/session' && down ? new Response('<h1>Cloudflare Tunnel error</h1>', { status: 530 }) : new Response('{}')))
    render(<Web store={memoryStore('tok')} fetch={fetch as never} />)
    expect(await screen.findByRole('heading', { name: "Can't reach your computer" })).toBeInTheDocument()
    expect(screen.queryByText(/Cloudflare/)).toBeNull()
    down = false
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { name: 'The desktop screens' })).toBeInTheDocument()
  })

  it('no network at all: the same screen', async () => {
    const fetch = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    })
    render(<Web store={memoryStore('tok')} fetch={fetch as never} />)
    expect(await screen.findByRole('heading', { name: "Can't reach your computer" })).toBeInTheDocument()
  })

  describe('a pairing link opened in another Android browser', () => {
    const BRAVE = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36'
    const FIREFOX = 'Mozilla/5.0 (Android 14; Mobile; rv:138.0) Gecko/138.0 Firefox/138.0'
    afterEach(() => {
      vi.restoreAllMocks()
      delete (navigator as { brave?: unknown }).brave
    })

    it('offers Chrome first, with the code carried along, and pairs nothing yet', async () => {
      vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(BRAVE)
      Object.defineProperty(navigator, 'brave', { value: {}, configurable: true })
      window.location.hash = '#pair=ABCD-EFGH'
      const fetch = server({})
      render(<Web store={memoryStore()} fetch={fetch as never} />)
      const chrome = await screen.findByRole('link', { name: 'Open in Chrome' })
      expect(chrome.getAttribute('href')).toMatch(/^intent:\/\/.*#pair=ABCD-EFGH#Intent;scheme=https;package=com\.android\.chrome;end$/)
      expect(fetch).not.toHaveBeenCalledWith('/pair', expect.anything())
    })

    it('Continue here pairs in this browser', async () => {
      vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(FIREFOX)
      window.location.hash = '#pair=ABCD-EFGH'
      const store = memoryStore()
      const fetch = server({ '/pair': () => new Response(JSON.stringify({ device: 'Pixel', token: 'tok' })) })
      render(<Web store={store} fetch={fetch as never} />)
      await userEvent.click(await screen.findByRole('button', { name: 'Continue here' }))
      expect(await screen.findByRole('heading', { name: 'The desktop screens' })).toBeInTheDocument()
      expect(store.value).toBe('tok')
    })

    it('Chrome itself pairs at once', async () => {
      vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(BRAVE) // Chrome's own user agent, without navigator.brave
      window.location.hash = '#pair=ABCD-EFGH'
      const fetch = server({ '/pair': () => new Response(JSON.stringify({ device: 'Pixel', token: 'tok' })) })
      render(<Web store={memoryStore()} fetch={fetch as never} />)
      expect(await screen.findByRole('heading', { name: 'The desktop screens' })).toBeInTheDocument()
      expect(screen.queryByRole('link', { name: 'Open in Chrome' })).toBeNull()
    })
  })

  it('offers the install after pairing, and not on the pair screen', async () => {
    captureInstallPrompt()
    const event = Object.assign(new Event('beforeinstallprompt', { cancelable: true }), { prompt: vi.fn(async () => undefined) })
    const store = memoryStore()
    const fetch = server({ '/pair': () => new Response(JSON.stringify({ device: 'Pixel', token: 'tok' })) })
    render(<Web store={store} fetch={fetch as never} />)
    await screen.findByLabelText('Pairing code')
    act(() => void window.dispatchEvent(event))
    expect(screen.queryByRole('button', { name: 'Install the app' })).toBeNull()
    await userEvent.type(screen.getByLabelText('Pairing code'), 'ABCD-EFGH')
    await userEvent.click(screen.getByRole('button', { name: 'Pair' }))
    expect(await screen.findByRole('heading', { name: 'The desktop screens' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Install the app' })).toBeInTheDocument()
  })
})
