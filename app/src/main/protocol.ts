// door-file://output/<jobId>/[sent/]<page>.png: the page images of a prepared job (or of the copy sent), served
// from HOME/jobs/output and nothing else. Pure; index.ts does the serving.
import { existsSync, realpathSync } from 'node:fs'
import { join, sep } from 'node:path'
import { isJobId, isPngName, materialPath } from './files'

export const MATERIAL_SCHEME = 'door-file'

/** The file a door-file request names, or null (answer 404). */
export function resolveMaterialRequest(url: string, home: string): string | null {
  // Encoded dots, slashes and backslashes have no business in a page name; the URL parser would fold them.
  if (/%2e|%2f|%5c/i.test(url)) return null
  let u: URL
  try {
    u = new URL(url)
  } catch {
    return null
  }
  if (u.protocol !== `${MATERIAL_SCHEME}:` || u.host !== 'output') return null
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

/**
 * door-file://profile/photo.jpg: the CV photo `save_photo` keeps, for the preview beside the Photo field
 * (the page may add `?v=` to see a new one). The one file, and only when, links resolved, it is still under
 * HOME/profile. The file the profile names may lie elsewhere; this is the copy the app itself keeps.
 */
export function resolvePhotoRequest(url: string, home: string): string | null {
  if (/%2e|%2f|%5c/i.test(url)) return null
  let u: URL
  try {
    u = new URL(url)
  } catch {
    return null
  }
  if (u.protocol !== `${MATERIAL_SCHEME}:` || u.host !== 'profile' || u.pathname !== '/photo.jpg') return null
  const candidate = join(home, 'profile', 'photo.jpg')
  try {
    if (!existsSync(candidate)) return null
    const root = realpathSync(join(home, 'profile'))
    return realpathSync(candidate).startsWith(root + sep) ? candidate : null
  } catch {
    return null
  }
}
