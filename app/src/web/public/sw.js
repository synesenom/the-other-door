// The phone app's service worker (#303): keeps the app's own code (the page, scripts, styles, fonts,
// icons) so it opens without a network and says it can't reach door. Never anything with data in it:
// /mcp, /files, /pair, /session and the manifest always go to the network.
const SHELL = 'door-shell-v1'
const NEVER = /^\/(mcp|files|pair|session|manifest\.webmanifest)(\/|$)/

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  const url = new URL(request.url)
  if (request.method !== 'GET' || url.origin !== self.location.origin || NEVER.test(url.pathname)) return
  if (request.mode === 'navigate') {
    // the newest page when online, the kept one when not
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone()
          if (response.ok) caches.open(SHELL).then((c) => c.put('/', copy))
          return response
        })
        .catch(() => caches.match('/')),
    )
    return
  }
  if (/^\/(assets|icons|licenses)\//.test(url.pathname) || url.pathname === '/sw.js') {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ||
          fetch(request).then((response) => {
            const copy = response.clone()
            if (response.ok) caches.open(SHELL).then((c) => c.put(request, copy))
            return response
          }),
      ),
    )
  }
})
