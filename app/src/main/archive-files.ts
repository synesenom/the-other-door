// The files of a data move (#222): where an export goes and which archive an import reads; and where a problem
// report goes (#593). All are chosen
// in dialogs the main process runs; the window gets the export's path back to show, and for an import only
// a one-shot token and the file's name, which `take` turns into the real path for import_data.
import { randomUUID } from 'node:crypto'
import { basename } from 'node:path'

interface Deps {
  showSaveDialog: (options: Record<string, unknown>) => Promise<{ canceled: boolean; filePath?: string }>
  showOpenDialog: (options: Record<string, unknown>) => Promise<{ canceled: boolean; filePaths: string[] }>
  exists: (path: string) => boolean
  realpath: (path: string) => Promise<string>
  /** Today as YYYY-MM-DD, for the suggested name. */
  today?: () => string
}

const FILTERS = [{ name: 'The other door export', extensions: ['tar.gz', 'tgz'] }]
const isArchive = (p: string) => /\.(tar\.gz|tgz)$/i.test(p)

export const defaultExportName = (day: string) => `door-export-${day}.tar.gz`
export const defaultReportName = (day: string) => `door-report-${day}.zip`

export function createArchiveFiles(deps: Deps) {
  const today = deps.today ?? (() => new Date().toISOString().slice(0, 10))
  // One import at a time: a new pick replaces the last.
  let pending: { token: string; path: string } | null = null

  return {
    /** Where to write an export: a new file the user named (export_data never replaces one). */
    async exportTarget(): Promise<{ path: string } | { canceled: true } | { error: string }> {
      // macOS's panel offers to replace an existing file and cannot be told not to; its message says why that is refused.
      const r = await deps.showSaveDialog({ title: 'Export your data', message: 'Choose a new name: an export never replaces a file.', defaultPath: defaultExportName(today()), filters: FILTERS })
      if (r.canceled || !r.filePath) return { canceled: true }
      const path = isArchive(r.filePath) ? r.filePath : `${r.filePath}.tar.gz`
      if (deps.exists(path)) return { error: `${basename(path)} is there already. An export never replaces a file, so nothing was written: choose another name.` }
      return { path }
    },

    /** Where to write a problem report (report_problem never replaces a file either). */
    async reportTarget(): Promise<{ path: string } | { canceled: true } | { error: string }> {
      const r = await deps.showSaveDialog({ title: 'Report a problem', message: 'Choose a new name: a report never replaces a file.', defaultPath: defaultReportName(today()), filters: [{ name: 'Problem report', extensions: ['zip'] }] })
      if (r.canceled || !r.filePath) return { canceled: true }
      const path = /\.zip$/i.test(r.filePath) ? r.filePath : `${r.filePath}.zip`
      if (deps.exists(path)) return { error: `${basename(path)} is there already. A report never replaces a file, so nothing was written: choose another name.` }
      return { path }
    },

    /** An archive to import, as a token and its name. */
    async pick(): Promise<{ token: string; name: string } | { canceled: true } | { error: string }> {
      const r = await deps.showOpenDialog({ title: 'Import data', properties: ['openFile'], filters: FILTERS })
      if (r.canceled || r.filePaths.length === 0) return { canceled: true }
      const chosen = r.filePaths[0]!
      const refused = { error: 'Choose an export, a .tar.gz file.' }
      if (!isArchive(chosen)) return refused
      const real = await deps.realpath(chosen)
      if (!isArchive(real)) return refused
      pending = { token: randomUUID(), path: real }
      return { token: pending.token, name: basename(chosen) }
    },

    /** The real path of a picked archive, once. */
    take(token: string): string | null {
      if (!pending || pending.token !== token) return null
      const { path } = pending
      pending = null
      return path
    },
  }
}

export type ArchiveFiles = ReturnType<typeof createArchiveFiles>
