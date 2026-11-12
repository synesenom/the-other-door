// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../testing'
import { DataMoves } from './DataMoves'

afterEach(cleanup)

function show() {
  const h = mockDoor({})
  const onImported = vi.fn()
  render(<DataMoves onImported={onImported} />)
  return { ...h, onImported }
}

describe('Your data', () => {
  it('Export writes where you said and says what went in', async () => {
    const { exportData } = show()
    exportData.mockResolvedValueOnce({ ok: true, data: { path: '/Users/ada/door-export-2026-10-30.tar.gz', files: 120, bytes: 3_500_000 } })
    await userEvent.click(screen.getByRole('button', { name: 'Export…' }))
    expect(await screen.findByText('Exported 120 files (3.5 MB) to door-export-2026-10-30.tar.gz.')).toBeInTheDocument()
  })

  it('a cancelled export says nothing; a refused one says why', async () => {
    const { exportData } = show()
    exportData.mockResolvedValueOnce({ ok: false, canceled: true })
    await userEvent.click(screen.getByRole('button', { name: 'Export…' }))
    expect(screen.queryByRole('alert')).toBeNull()
    exportData.mockResolvedValueOnce({ ok: false, error: 'x.tar.gz is there already' })
    await userEvent.click(screen.getByRole('button', { name: 'Export…' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('there already')
  })

  it('Import names the file and what it replaces, and imports only after the yes', async () => {
    const { pickArchive, importData, onImported } = show()
    pickArchive.mockResolvedValueOnce({ token: 't1', name: 'door-export.tar.gz' })
    importData.mockResolvedValueOnce({ ok: true, data: { files: 120, backup_dir: '/home/backups/2026-10-30T10-00', warnings: ['config cv_template: /Users/old/cv.tex is not on this computer'] } })
    await userEvent.click(screen.getByRole('button', { name: 'Import…' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('door-export.tar.gz')
    expect(dialog).toHaveTextContent('replaces your profile and jobs')
    expect(dialog).toHaveTextContent('kept as a backup first, so nothing is lost')
    expect(dialog).toHaveTextContent('Google Drive')
    expect(importData).not.toHaveBeenCalled()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Import' }))
    expect(importData).toHaveBeenCalledWith('t1')
    expect(await screen.findByText('Imported 120 files. What was here is kept in /home/backups/2026-10-30T10-00.')).toBeInTheDocument()
    expect(screen.getByText(/cv_template/)).toBeInTheDocument()
    expect(onImported).toHaveBeenCalled()
  })

  it('Cancel in the dialog imports nothing', async () => {
    const { pickArchive, importData } = show()
    pickArchive.mockResolvedValueOnce({ token: 't1', name: 'a.tar.gz' })
    await userEvent.click(screen.getByRole('button', { name: 'Import…' }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Cancel' }))
    expect(importData).not.toHaveBeenCalled()
  })

  it('a refused archive or a failed import says why', async () => {
    const { pickArchive, importData } = show()
    pickArchive.mockResolvedValueOnce({ error: 'Choose an export, a .tar.gz file.' })
    await userEvent.click(screen.getByRole('button', { name: 'Import…' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose an export')
    pickArchive.mockResolvedValueOnce({ token: 't2', name: 'a.tar.gz' })
    importData.mockResolvedValueOnce({ ok: false, error: 'a run is in progress' })
    await userEvent.click(screen.getByRole('button', { name: 'Import…' }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Import' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('a run is in progress')
  })
})
