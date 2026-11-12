// Share → door (issue 334): what another app shared to the installed phone app (the manifest's
// share_target opens /share?title&text&url). A link to import, or the ad's own text.

const LINK = /https?:\/\/[^\s<>"']+/

export type Shared = { url: string } | { text: string }

export function sharedFrom(search: string): Shared | null {
  const q = new URLSearchParams(search)
  const url = (q.get('url') ?? '').trim()
  if (url) return /^https?:\/\//i.test(url) ? { url } : null
  const text = (q.get('text') ?? '').trim()
  const link = LINK.exec(text)?.[0]
  if (link) return { url: link }
  return text ? { text } : null
}
