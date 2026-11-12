// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { mockDoor } from '../testing'
import { ReportProblem } from './ReportProblem'

afterEach(cleanup)

function show() {
  const h = mockDoor({})
  render(<ReportProblem />)
  return h
}

describe('Report a problem', () => {
  it('says what it saves and what it never holds, before anything is saved', () => {
    const { reportProblem } = show()
    expect(screen.getByText(/^Saves one file to send when something does not work/)).toHaveTextContent('No CV, profile, job ads or applications; emails and folder names are hidden.')
    expect(reportProblem).not.toHaveBeenCalled()
  })

  it('saves where the dialog said and says whom to send it to', async () => {
    const { reportProblem, call } = show()
    reportProblem.mockResolvedValueOnce({ ok: true, data: { path: '/Users/ada/Desktop/door-report-2026-10-26.zip', files: ['README.txt'], bytes: 4000 } })
    await userEvent.click(screen.getByRole('button', { name: 'Save logs…' }))
    expect(await screen.findByText('Saved as door-report-2026-10-26.zip. Send it to enys.mones@gmail.com.')).toBeInTheDocument()
    expect(call).not.toHaveBeenCalled()
  })

  it('a cancelled dialog says nothing; a refused save says why', async () => {
    const { reportProblem } = show()
    await userEvent.click(screen.getByRole('button', { name: 'Save logs…' }))
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.queryByText(/^Saved as/)).toBeNull()
    reportProblem.mockResolvedValueOnce({ ok: false, error: 'r.zip is there already. A report never replaces a file, so nothing was written: choose another name.' })
    await userEvent.click(screen.getByRole('button', { name: 'Save logs…' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('r.zip is there already.')
  })
})
