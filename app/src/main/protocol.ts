// door-file://output/<jobId>/[sent/]<page>.png: the page images of a prepared job (or of the copy sent), served
// from HOME/jobs/output, and the previews of a CV style, and nothing else. Pure; index.ts does the serving.
import { join } from 'node:path'
import { contained, isJobId, isPngName, materialPath } from './files'

export const MATERIAL_SCHEME = 'door-file'

/** The file a door-file request names, or null (answer 404). */
export function resolveMaterialRequest(url: string, home: string): string | null {
  const u = parse(url, 'output')
  if (!u) return null
  const parts = u.pathname.split('/').filter((_, i) => i > 0)
  const sent = parts.length === 3 && parts[1] === 'sent'
  if (parts.length !== 2 && !sent) return null
  let jobId: string
  let file: string
  try {
    jobId = decodeURIComponent(parts[0]!)
    file = decodeURIComponent(parts[parts.length - 1]!)
  } catch {
    return null
  }
  if (!isJobId(jobId) || !isPngName(file)) return null
  return materialPath(home, jobId, file, sent)
}

/** The URL of a door-file request for `host`, or null: no encoded dots or slashes, which the URL parser would fold. */
function parse(url: string, host: string): URL | null {
  if (/%2e|%2f|%5c/i.test(url)) return null
  try {
    const u = new URL(url)
    return u.protocol === `${MATERIAL_SCHEME}:` && u.host === host ? u : null
  } catch {
    return null
  }
}

/**
 * door-file://profile/photo.jpg: the CV photo `save_photo` keeps, for the preview beside the Photo field
 * (the page may add `?v=` to see a new one). The one file, and only when, links resolved, it is still under
 * HOME/profile. The file the profile names may lie elsewhere; this is the copy the app itself keeps.
 */
export function resolvePhotoRequest(url: string, home: string): string | null {
  const u = parse(url, 'profile')
  if (!u || u.pathname !== '/photo.jpg') return null
  return contained(join(home, 'profile', 'photo.jpg'), join(home, 'profile'))
}

/**
 * door-file://style/<default|like>/<cv|letter>_page_<N>.png: the previews of a CV style (`show_style`), served from
 * HOME/.style/preview/<style>/ and nothing else, the page adding `?v=` (the set's version) so a re-made image is
 * fetched again. Links resolved, the file must still lie under that folder.
 */
export function resolveStylePreviewRequest(url: string, home: string): string | null {
  const u = parse(url, 'style')
  if (!u) return null
  const parts = u.pathname.split('/').filter((_, i) => i > 0)
  if (parts.length !== 2) return null
  const [style, file] = parts as [string, string]
  if (!['default', 'like', 'draft', 'original'].includes(style) || !/^(cv|letter)_page_\d+\.png$/.test(file)) return null
  const root = join(home, '.style', 'preview')
  return contained(join(root, style, file), root)
}
