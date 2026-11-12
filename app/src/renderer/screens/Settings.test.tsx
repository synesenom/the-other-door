// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../testing'
import { Settings } from './Settings'
import { RemoteContext } from '../remote'

/** The calls a test is about: the phone row's status read (issue 444) happens on every open. */
const calls = (call: { mock: { calls: unknown[][] } }) => call.mock.calls.filter((c) => c[0] !== 'phone_status')

afterEach(cleanup)

function show(where: 'real' | 'demo' | 'sandbox' = 'real', remote = false, update?: unknown) {
  const h = mockDoor({})
  if (update) h.checkUpdate.mockResolvedValue(update as never)
  const props = {
    doctor: null,
    drive: null,
    where,
    home: '/Users/ada/door-data',
    version: '0.1.0',
    email: 'ada@example.com',
    onRecheck: vi.fn(),
    onDriveChanged: vi.fn(),
    onDataChanged: vi.fn(),
  }
  render(
    <RemoteContext.Provider value={remote}>
      <Settings {...props} />
    </RemoteContext.Provider>,
  )
  return { ...h, ...props }
}

describe('Settings', () => {
  it('reads doctor and the profile when it opens, and nothing else', () => {
    const { onRecheck, call } = show()
    expect(screen.getByRole('heading', { name: 'Settings', level: 1 })).toBeInTheDocument()
    expect(onRecheck).toHaveBeenCalledTimes(1)
    expect(calls(call).map((c) => c[0])).toEqual(['show_profile']) // Risky sources
  })

  it('has the Connections section with Claude and Google Drive', () => {
    show()
    const section = screen.getByRole('region', { name: 'Connections' })
    expect(within(section).getByRole('listitem', { name: 'Claude' })).toBeInTheDocument()
    expect(within(section).getByRole('listitem', { name: 'Google Drive' })).toBeInTheDocument()
  })

  it('Your data: says where the data folder is, and the path shows it; Export and Import', async () => {
    const { showHome } = show()
    const section = screen.getByRole('region', { name: 'Your data' })
    expect(within(section).getByText(/^Your profile and jobs are stored in/)).toHaveTextContent(
      'Your profile and jobs are stored in /Users/ada/door-data. Export saves them in one file, to move to another computer or keep a copy; Import replaces them with the ones in such a file.',
    )
    expect(within(section).getAllByRole('button').map((b) => b.textContent)).toEqual(['/Users/ada/door-data', 'Export…', 'Import…'])
    await userEvent.click(within(section).getByRole('button', { name: '/Users/ada/door-data' }))
    expect(showHome).toHaveBeenCalledWith()
    within(section).getByRole('button', { name: '/Users/ada/door-data' }).focus()
    await userEvent.keyboard('{Enter}')
    expect(showHome).toHaveBeenCalledTimes(2)
  })

  it('lists its parts beside them', () => {
    show()
    const parts = screen.getByRole('navigation', { name: 'Sections' })
    expect(within(parts).getAllByRole('link').map((a) => a.textContent)).toEqual(['Connections', 'Risky sources', 'Your data', 'Appearance', 'Documentation', 'Report a problem'])
  })

  it('opened at Report a problem (the sidebar\'s line): scrolled to it', () => {
    mockDoor({})
    const scrolled: Element[] = []
    const before = Element.prototype.scrollIntoView // jsdom has none
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this)
    }
    try {
      render(<Settings doctor={null} drive={null} where="real" at="report" onRecheck={vi.fn()} onDriveChanged={vi.fn()} onDataChanged={vi.fn()} />)
      expect(scrolled).toEqual([screen.getByRole('region', { name: 'Report a problem' })])
    } finally {
      Element.prototype.scrollIntoView = before
    }
  })

  it('a saved report is said to the app, so the sidebar reads the summary again', async () => {
    const h = mockDoor({})
    const onReported = vi.fn()
    render(<Settings doctor={null} drive={null} where="real" onReported={onReported} onRecheck={vi.fn()} onDriveChanged={vi.fn()} onDataChanged={vi.fn()} />)
    h.reportProblem.mockResolvedValueOnce({ ok: false, canceled: true })
    const report = screen.getByRole('region', { name: 'Report a problem' })
    await userEvent.click(within(report).getByRole('button', { name: 'Save logs…' }))
    expect(onReported).not.toHaveBeenCalled()
    h.reportProblem.mockResolvedValueOnce({ ok: true, data: { path: '/tmp/r.zip', files: [], bytes: 1 } })
    await userEvent.click(within(report).getByRole('button', { name: 'Save logs…' }))
    await screen.findByText(/^Saved as r\.zip/)
    expect(onReported).toHaveBeenCalledTimes(1)
  })

  it('the phone has no list of parts', () => {
    show('real', true)
    expect(screen.queryByRole('navigation', { name: 'Sections' })).toBeNull()
  })

  it('has Your data', () => {
    show()
    expect(screen.getByRole('region', { name: 'Your data' })).toHaveTextContent('Export…')
  })

  it('Appearance: the system theme until another is chosen, then that one', async () => {
    show()
    const section = screen.getByRole('region', { name: 'Appearance' })
    expect(within(section).getByRole('radio', { name: 'Same as the system' })).toBeChecked()
    await userEvent.click(within(section).getByRole('radio', { name: 'Dark' }))
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
    await userEvent.click(within(section).getByRole('radio', { name: 'Same as the system' }))
    expect(document.documentElement).not.toHaveAttribute('data-theme')
  })

  it('on the phone: no export, import or report; it says these are done on the computer running The other door', () => {
    show('real', true)
    const computer = screen.getByRole('region', { name: 'This computer' })
    expect(within(computer).getByText(/where it is installed/)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Your data' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Save logs…' })).toBeNull()
  })

  it('on the phone: only Appearance and where the data is; no connections, no doctor', () => {
    const { onRecheck, call } = show('real', true)
    expect(screen.getByRole('region', { name: 'Appearance' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'This computer' })).toHaveTextContent('/Users/ada/door-data')
    expect(screen.queryByRole('region', { name: 'Connections' })).toBeNull()
    expect(onRecheck).not.toHaveBeenCalled()
    expect(call).not.toHaveBeenCalled()
  })

})

describe('Settings: Version', () => {
  const none = { enabled: true, checked: true, current: '0.1.0', available: false } as const
  const newer = { enabled: true, checked: true, current: '0.1.0', available: true, version: '0.1.1', url: 'https://example.com/releases/v0.1.1' } as const

  it('has no Version section when there is no feed', async () => {
    const { checkUpdate } = show()
    await vi.waitFor(() => expect(checkUpdate).toHaveBeenCalledWith())
    expect(screen.queryByRole('region', { name: 'Version' })).toBeNull()
  })

  it('says a newer version is available and opens its page', async () => {
    const { openExternal } = show('real', false, newer)
    const section = await screen.findByRole('region', { name: 'Version' })
    expect(within(section).getByText('Version 0.1.0')).toBeInTheDocument()
    expect(within(section).getByText('Version 0.1.1 is available')).toBeInTheDocument()
    await userEvent.click(within(section).getByRole('button', { name: 'Download' }))
    expect(openExternal).toHaveBeenCalledWith('https://example.com/releases/v0.1.1')
  })

  it('shows no notice for the latest; Check for updates asks afresh', async () => {
    const { checkUpdate } = show('real', false, none)
    const section = await screen.findByRole('region', { name: 'Version' })
    expect(within(section).queryByText(/is available/)).toBeNull()
    await userEvent.click(within(section).getByRole('button', { name: 'Check for updates' }))
    expect(checkUpdate).toHaveBeenLastCalledWith(true)
    expect(await within(section).findByText('You have the latest version')).toBeInTheDocument()
  })

  it('a manual check that fails says so; an automatic one says nothing', async () => {
    const failed = { enabled: true, checked: false, current: '0.1.0' }
    const { checkUpdate } = show('real', false, failed)
    const section = await screen.findByRole('region', { name: 'Version' })
    expect(within(section).queryByText(/Couldn't check/)).toBeNull()
    await userEvent.click(within(section).getByRole('button', { name: 'Check for updates' }))
    expect(checkUpdate).toHaveBeenLastCalledWith(true)
    expect(await within(section).findByText("Couldn't check just now")).toBeInTheDocument()
  })

  it('the phone never asks', () => {
    const { checkUpdate } = show('real', true, newer)
    expect(checkUpdate).not.toHaveBeenCalled()
    expect(screen.queryByRole('region', { name: 'Version' })).toBeNull()
  })
})
