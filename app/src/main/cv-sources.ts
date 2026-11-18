// The files a CV draft is read from. The window never names a path: the main process runs the
// open dialog, or the preload hands over what the user dropped (Electron's own path of a dropped
// File; the page never sees it), keeps each path under a random token, and the window sends the
// tokens back. The registry is never readable from outside (there is no getter), and is cleared when
// the wizard closes. A file choice always goes through one of those two and a token like this.
import { randomUUID } from 'node:crypto'
import { basename, extname } from 'node:path'
import { checkPicked } from './files'
import { isExternalUrl } from './security'

export const MAX_CV_BYTES = 25 * 1024 * 1024
export const CV_EXTENSIONS = ['.pdf', '.docx', '.md', '.markdown', '.txt']
export const LINKEDIN_HINT = "LinkedIn pages can't be read; save your profile as a PDF (More → Save to PDF) and add that file."

export interface CvFile {
  token: string
  name: string
  size: number
}
export interface PickResult {
  files: CvFile[]
  refused: { name: string; reason: string }[]
}

interface Deps {
  showOpenDialog(options: { properties: string[]; filters: { name: string; extensions: string[] }[] }): Promise<{ canceled: boolean; filePaths: string[] }>
  stat(path: string): Promise<{ size: number }>
  /** Resolves links, so the checks (and the server) see the file actually read; identity when absent. */
  realpath?(path: string): Promise<string>
}

/** Why a file cannot be used, or null; the server is handed the real path checked here (a pick later swapped for a link is refused). */
async function problem(path: string, deps: Deps): Promise<{ reason: string } | { reason: null; size: number; real: string }> {
  const checked = await checkPicked(
    path,
    {
      extensions: CV_EXTENSIONS.map((e) => e.slice(1)),
      maxBytes: MAX_CV_BYTES,
      wrongType: 'Only PDF, DOCX, Markdown and text files can be read.',
      tooBig: 'That file is over 25 MB.',
    },
    deps,
  )
  return checked.ok ? { reason: null, size: checked.size, real: checked.real } : { reason: checked.error }
}

export function createCvSources(deps: Deps) {
  const registry = new Map<string, string>()
  const add = async (paths: string[]): Promise<PickResult> => {
    const result: PickResult = { files: [], refused: [] }
    for (const path of paths) {
      const name = basename(path)
      const p = await problem(path, deps)
      if (p.reason !== null) {
        result.refused.push({ name, reason: p.reason })
        continue
      }
      const token = randomUUID()
      registry.set(token, path)
      result.files.push({ token, name, size: p.size })
    }
    return result
  }
  return {
    async pick(): Promise<PickResult> {
      const answer = await deps.showOpenDialog({
        properties: ['openFile', 'multiSelections'],
        filters: [{ name: 'CV files', extensions: CV_EXTENSIONS.map((e) => e.slice(1)) }],
      })
      return answer.canceled ? { files: [], refused: [] } : add(answer.filePaths)
    },
    add,
    async resolve(tokens: string[]): Promise<{ ok: true; paths: string[] } | { ok: false; error: string }> {
      const paths: string[] = []
      for (const token of tokens) {
        const path = registry.get(token)
        if (!path) return { ok: false, error: 'A chosen file is no longer available; add it again.' }
        const p = await problem(path, deps)
        if (p.reason !== null) return { ok: false, error: `${basename(path)}: ${p.reason}` }
        paths.push(p.real)
      }
      return { ok: true, paths }
    },
    clear(): void {
      registry.clear()
    },
  }
}

export type CvSources = ReturnType<typeof createCvSources>

/** The pages a draft may read: http(s) only, and not LinkedIn, which refuses logged-out readers. */
export function checkUrls(urls: string[]): { ok: true } | { ok: false; error: string } {
  for (const url of urls) {
    if (!isExternalUrl(url)) return { ok: false, error: `${url} is not a web page address (http or https).` }
    // A trailing dot is the same host ("linkedin.com." is linkedin.com).
    const host = new URL(url).hostname.toLowerCase().replace(/\.+$/, '')
    if (host === 'linkedin.com' || host.endsWith('.linkedin.com')) return { ok: false, error: LINKEDIN_HINT }
  }
  return { ok: true }
}
