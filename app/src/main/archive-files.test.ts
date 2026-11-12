import { describe, expect, it, vi } from 'vitest'
import { createArchiveFiles, defaultExportName, defaultReportName } from './archive-files'

function setup(opts: { save?: string | null; open?: string[]; existing?: string[]; real?: Record<string, string> } = {}) {
  const showSaveDialog = vi.fn(async () => (opts.save === null ? { canceled: true } : { canceled: false, filePath: opts.save ?? '/Users/ada/door-export-2026-10-30.tar.gz' }))
  const showOpenDialog = vi.fn(async () => (opts.open ? { canceled: false, filePaths: opts.open } : { canceled: true, filePaths: [] }))
  const exists = vi.fn((p: string) => (opts.existing ?? []).includes(p))
  const realpath = vi.fn(async (p: string) => opts.real?.[p] ?? p)
  const files = createArchiveFiles({ showSaveDialog, showOpenDialog, exists, realpath, today: () => '2026-10-30' })
  return { files, showSaveDialog, showOpenDialog, exists, realpath }
}

describe('defaultExportName', () => {
  it('names the export by the day', () => {
    expect(defaultExportName('2026-10-30')).toBe('door-export-2026-10-30.tar.gz')
  })
})

describe('exportTarget', () => {
  it('asks where, suggesting the day\'s name, and answers the chosen path', async () => {
    const { files, showSaveDialog } = setup()
    expect(await files.exportTarget()).toEqual({ path: '/Users/ada/door-export-2026-10-30.tar.gz' })
    expect(showSaveDialog).toHaveBeenCalledWith(expect.objectContaining({ defaultPath: 'door-export-2026-10-30.tar.gz', message: 'Choose a new name: an export never replaces a file.' }))
  })

  it('a cancelled dialog is no target', async () => {
    expect(await setup({ save: null }).files.exportTarget()).toEqual({ canceled: true })
  })

  it('adds .tar.gz to a name without it', async () => {
    expect(await setup({ save: '/Users/ada/my-backup' }).files.exportTarget()).toEqual({ path: '/Users/ada/my-backup.tar.gz' })
  })

  it('refuses a file that is there already: an export never overwrites', async () => {
    const r = await setup({ existing: ['/Users/ada/door-export-2026-10-30.tar.gz'] }).files.exportTarget()
    expect(r).toEqual({ error: 'door-export-2026-10-30.tar.gz is there already. An export never replaces a file, so nothing was written: choose another name.' })
  })
})

describe('pick and take', () => {
  it('a picked archive comes back as a token and its name, never its path', async () => {
    const { files } = setup({ open: ['/Users/ada/secret/door-export.tar.gz'] })
    const r = await files.pick()
    expect(r).toEqual({ token: expect.any(String), name: 'door-export.tar.gz' })
    expect(JSON.stringify(r)).not.toContain('secret')
  })

  it('take hands the real path over once', async () => {
    const { files } = setup({ open: ['/Users/ada/link.tgz'], real: { '/Users/ada/link.tgz': '/Volumes/usb/door.tgz' } })
    const r = (await files.pick()) as { token: string }
    expect(files.take(r.token)).toBe('/Volumes/usb/door.tgz')
    expect(files.take(r.token)).toBeNull()
    expect(files.take('made-up')).toBeNull()
  })

  it('refuses what is not an archive, also at its real target', async () => {
    expect(await setup({ open: ['/Users/ada/cv.pdf'] }).files.pick()).toEqual({ error: 'Choose an export, a .tar.gz file.' })
    expect(await setup({ open: ['/Users/ada/x.tar.gz'], real: { '/Users/ada/x.tar.gz': '/etc/passwd' } }).files.pick()).toEqual({ error: 'Choose an export, a .tar.gz file.' })
  })

  it('a cancelled dialog is no pick, and a new pick replaces the old token', async () => {
    expect(await setup().files.pick()).toEqual({ canceled: true })
    const { files } = setup({ open: ['/a/one.tar.gz'] })
    const first = (await files.pick()) as { token: string }
    await files.pick()
    expect(files.take(first.token)).toBeNull()
  })
})

describe('reportTarget', () => {
  it('asks where, suggesting the day\'s report name, and answers the chosen path', async () => {
    const { files, showSaveDialog } = setup({ save: '/Users/ada/Desktop/door-report-2026-10-30.zip' })
    expect(defaultReportName('2026-10-30')).toBe('door-report-2026-10-30.zip')
    expect(await files.reportTarget()).toEqual({ path: '/Users/ada/Desktop/door-report-2026-10-30.zip' })
    expect(showSaveDialog).toHaveBeenCalledWith(expect.objectContaining({ title: 'Report a problem', defaultPath: 'door-report-2026-10-30.zip', filters: [{ name: 'Problem report', extensions: ['zip'] }] }))
  })

  it('a cancelled dialog is no target; a name without .zip gets it', async () => {
    expect(await setup({ save: null }).files.reportTarget()).toEqual({ canceled: true })
    expect(await setup({ save: '/Users/ada/for-the-helper' }).files.reportTarget()).toEqual({ path: '/Users/ada/for-the-helper.zip' })
  })

  it('refuses a file that is there already', async () => {
    const r = await setup({ save: '/Users/ada/door-report-2026-10-30.zip', existing: ['/Users/ada/door-report-2026-10-30.zip'] }).files.reportTarget()
    expect(r).toEqual({ error: 'door-report-2026-10-30.zip is there already. A report never replaces a file, so nothing was written: choose another name.' })
  })
})
