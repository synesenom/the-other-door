// The service worker (public/sw.js) run in a stand-in of its global scope: what it answers a page load with.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'

const SOURCE = readFileSync(resolve(__dirname, 'public/sw.js'), 'utf8')

function worker(network: () => Promise<Response>, kept: Response | undefined) {
  const handlers: Record<string, (e: unknown) => void> = {}
  const cache = { put: vi.fn(async () => undefined) }
  const scope = {
    location: { origin: 'https://door.example' },
    addEventListener: (type: string, fn: (e: unknown) => void) => (handlers[type] = fn),
    skipWaiting: () => undefined,
    clients: { claim: async () => undefined },
  }
  const caches = { match: vi.fn(async () => kept?.clone()), open: vi.fn(async () => cache), keys: async () => [], delete: async () => true }
  new Function('self', 'caches', 'fetch', SOURCE)(scope, caches, network)
  return async (path: string) => {
    let answer: Promise<Response> | undefined
    handlers.fetch({ request: { method: 'GET', mode: 'navigate', url: `https://door.example${path}` }, respondWith: (p: Promise<Response>) => (answer = p) })
    return answer!
  }
}

describe('the service worker, opening the app', () => {
  it("the tunnel's own error page (nothing behind it) gives way to the kept app, which says so in its words", async () => {
    const load = worker(async () => new Response('Cloudflare Tunnel error', { status: 530 }), new Response('the kept app'))
    expect(await (await load('/')).text()).toBe('the kept app')
  })

  it('no network at all: the kept app', async () => {
    const load = worker(async () => Promise.reject(new TypeError('offline')), new Response('the kept app'))
    expect(await (await load('/')).text()).toBe('the kept app')
  })

  it('nothing kept yet: the error page as it came', async () => {
    const load = worker(async () => new Response('Cloudflare Tunnel error', { status: 530 }), undefined)
    expect((await load('/')).status).toBe(530)
  })

  it('a working computer: the newest page', async () => {
    const load = worker(async () => new Response('the new app'), new Response('the kept app'))
    expect(await (await load('/')).text()).toBe('the new app')
  })
})
