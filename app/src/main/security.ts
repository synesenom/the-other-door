// Pure helpers behind the window's security settings (see index.ts).

/** Content-Security-Policy for the renderer: its own files only, no eval. */
export function cspHeader(opts: { dev?: boolean } = {}): string {
  const connect = opts.dev ? "'self' ws://localhost:* http://localhost:*" : "'self'"
  return [
    "default-src 'self'",
    // React's inline style props need 'unsafe-inline' for styles; scripts stay strict.
    "style-src 'self' 'unsafe-inline'",
    // The dev page runs React's refresh preamble, an inline script; the packaged page runs none.
    opts.dev ? "script-src 'self' 'unsafe-inline'" : "script-src 'self'",
    "img-src 'self' data: door-file:",
    "font-src 'self'",
    `connect-src ${connect}`,
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'none'",
  ].join('; ')
}

/** A navigation inside the window is allowed only to the app's own page. */
export function isAllowedNavigation(target: string, appUrl: string): boolean {
  try {
    const t = new URL(target)
    const a = new URL(appUrl)
    if (t.protocol !== a.protocol) return false
    if (t.protocol === 'file:') return t.pathname === a.pathname
    return t.origin === a.origin
  } catch {
    return false
  }
}

/** Links the app opens in the system browser: http(s) only. */
export function isExternalUrl(value: unknown): value is string {
  if (typeof value !== 'string') return false
  try {
    const u = new URL(value)
    return u.protocol === 'https:' || u.protocol === 'http:'
  } catch {
    return false
  }
}
