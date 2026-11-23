// @vitest-environment jsdom
import { act, cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../testing'
import { Settings } from './Settings'
import { RemoteContext } from '../remote'

/** The calls a test is about: the phone row's status read (issue 444) happens on every open. */
const calls = (call: { mock: { calls: unknown[][] } }) => call.mock.calls.filter((c) => c[0] !== 'phone_status')

afterEach(cleanup)

function show(where: 'production' | 'staging' | 'sandbox' = 'production', remote = false, update?: unknown) {
  const h = mockDoor({})
  if (update) h.actions['check-update'].mockResolvedValue(update as never)
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
    const { actions } = show()
    const showHome = actions['show-home']
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

  it('has no list of parts: a page about one screen tall', () => {
    show()
    expect(screen.queryByRole('navigation', { name: 'Sections' })).toBeNull()
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(['Connections', 'Risky sources', 'Your data', 'Appearance', 'Help'])
  })

  it('Help holds the version, the documents and the report button', async () => {
    show('production', false, { enabled: true, mode: 'install', checked: true, current: '0.1.0', available: false })
    const help = await screen.findByRole('region', { name: 'Help' })
    expect(await within(help).findByText('Version 0.1.0')).toBeInTheDocument()
    expect(within(help).getByRole('button', { name: 'Legal disclaimer' })).toBeInTheDocument()
    expect(within(help).getByRole('button', { name: 'Save logs…' })).toBeInTheDocument()
    for (const gone of ['Documentation', 'Report a problem', 'Version']) expect(screen.queryByRole('heading', { name: gone })).toBeNull()
  })

  it('opened at Report a problem (the sidebar\'s line): scrolled to it', () => {
    mockDoor({})
    const scrolled: Element[] = []
    const before = Element.prototype.scrollIntoView // jsdom has none
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this)
    }
    try {
      render(<Settings doctor={null} drive={null} where="production" at="report" onRecheck={vi.fn()} onDriveChanged={vi.fn()} onDataChanged={vi.fn()} />)
      const help = screen.getByRole('region', { name: 'Help' })
      expect(scrolled).toHaveLength(1)
      expect(help.contains(scrolled[0])).toBe(true)
      expect(within(scrolled[0] as HTMLElement).getByRole('button', { name: 'Save logs…' })).toBeInTheDocument()
    } finally {
      Element.prototype.scrollIntoView = before
    }
  })

  it('a saved report is said to the app, so the sidebar reads the summary again', async () => {
    const h = mockDoor({})
    const onReported = vi.fn()
    render(<Settings doctor={null} drive={null} where="production" onReported={onReported} onRecheck={vi.fn()} onDriveChanged={vi.fn()} onDataChanged={vi.fn()} />)
    h.actions['report-problem'].mockResolvedValueOnce({ ok: false, canceled: true })
    const report = screen.getByRole('region', { name: 'Help' })
    await userEvent.click(within(report).getByRole('button', { name: 'Save logs…' }))
    expect(onReported).not.toHaveBeenCalled()
    h.actions['report-problem'].mockResolvedValueOnce({ ok: true, data: { path: '/tmp/r.zip', files: [], bytes: 1 } })
    await userEvent.click(within(report).getByRole('button', { name: 'Save logs…' }))
    await screen.findByText(/^Saved as r\.zip/)
    expect(onReported).toHaveBeenCalledTimes(1)
  })

  it('the phone has no Help', () => {
    show('production', true)
    expect(screen.queryByRole('region', { name: 'Help' })).toBeNull()
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
    show('production', true)
    const computer = screen.getByRole('region', { name: 'This computer' })
    expect(within(computer).getByText(/where it is installed/)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Your data' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Save logs…' })).toBeNull()
  })

  it('on the phone: only Appearance and where the data is; no connections, no doctor', () => {
    const { onRecheck, call } = show('production', true)
    expect(screen.getByRole('region', { name: 'Appearance' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'This computer' })).toHaveTextContent('/Users/ada/door-data')
    expect(screen.queryByRole('region', { name: 'Connections' })).toBeNull()
    expect(onRecheck).not.toHaveBeenCalled()
    expect(call).not.toHaveBeenCalled()
  })

})

describe('Settings: Version', () => {
  const none = { enabled: true, mode: 'install', checked: true, current: '0.1.0', available: false } as const
  const link = { enabled: true, mode: 'link', checked: true, current: '0.1.0', available: true, version: '0.1.1', url: 'https://example.com/releases/v0.1.1', state: 'idle' } as const
  const downloading = { enabled: true, mode: 'install', checked: true, current: '0.1.0', available: true, version: '0.1.1', url: 'https://example.com/r', state: 'downloading' } as const
  const downloaded = { ...downloading, state: 'downloaded' } as const

  it('says no version when updates are off', async () => {
    const { actions } = show()
    const checkUpdate = actions['check-update']
    await vi.waitFor(() => expect(checkUpdate).toHaveBeenCalledWith())
    expect(within(screen.getByRole('region', { name: 'Help' })).queryByText(/^Version /)).toBeNull()
  })

  it('a build that cannot install says a newer version is available and opens its page', async () => {
    const { actions } = show('production', false, link)
    const openExternal = actions['open-external']
    const section = await screen.findByRole('region', { name: 'Help' })
    expect(await within(section).findByText('Version 0.1.1 is available')).toBeInTheDocument()
    const download = await within(section).findByRole('button', { name: 'Download' })
    expect(download).toHaveClass('go')
    await userEvent.click(download)
    expect(openExternal).toHaveBeenCalledWith('https://example.com/releases/v0.1.1')
  })

  it('with nothing newer: only the version, nothing to press (the app checks by itself)', async () => {
    show('production', false, none)
    const section = await screen.findByRole('region', { name: 'Help' })
    expect(await within(section).findByText('Version 0.1.0')).toBeInTheDocument()
    expect(within(section).queryByRole('button', { name: /Download|Restart/ })).toBeNull()
  })

  it('says it is downloading, with no Download link', async () => {
    show('production', false, downloading)
    const section = await screen.findByRole('region', { name: 'Help' })
    expect(await within(section).findByText('Downloading 0.1.1')).toBeInTheDocument()
    expect(within(section).queryByRole('button', { name: 'Download' })).toBeNull()
  })

  it('offers a restart once downloaded', async () => {
    const { actions } = show('production', false, downloaded)
    const installUpdate = actions['install-update']
    const section = await screen.findByRole('region', { name: 'Help' })
    await userEvent.click(await within(section).findByRole('button', { name: 'Restart to update to 0.1.1' }))
    expect(installUpdate).toHaveBeenCalledTimes(1)
  })

  it('follows the state the app pushes', async () => {
    const h = show('production', false, downloading)
    const section = await screen.findByRole('region', { name: 'Help' })
    expect(await within(section).findByText('Downloading 0.1.1')).toBeInTheDocument()
    act(() => h.pushUpdate(downloaded))
    expect(await within(section).findByRole('button', { name: 'Restart to update to 0.1.1' })).toBeInTheDocument()
  })

})
