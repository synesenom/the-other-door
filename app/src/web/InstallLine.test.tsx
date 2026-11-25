// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { InstallLine } from './InstallLine'
import { captureInstallPrompt } from './install'

const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1'

function fakeEvent() {
  return Object.assign(new Event('beforeinstallprompt', { cancelable: true }), { prompt: vi.fn(async () => undefined) })
}

beforeEach(() => {
  localStorage.clear()
  window.matchMedia = vi.fn().mockReturnValue({ matches: false }) as never
})
afterEach(() => {
  cleanup()
  window.dispatchEvent(new Event('appinstalled')) // forgets a kept prompt
  vi.restoreAllMocks()
})

describe('InstallLine', () => {
  it('shows Install the app after the browser offers it; the tap prompts; appinstalled removes it', async () => {
    captureInstallPrompt()
    const e = fakeEvent()
    render(<InstallLine />)
    expect(screen.queryByRole('button', { name: 'Install the app' })).toBeNull()
    act(() => void window.dispatchEvent(e))
    const names = (await screen.findAllByRole('button')).map((b) => b.textContent)
    expect(names).toEqual(['Not now', 'Install the app'])
    await userEvent.click(screen.getByRole('button', { name: 'Install the app' }))
    expect(e.prompt).toHaveBeenCalledTimes(1)
    act(() => void window.dispatchEvent(new Event('appinstalled')))
    expect(screen.queryByRole('button', { name: 'Install the app' })).toBeNull()
  })

  it('iPhone Safari: the Share words and no install button', () => {
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(IPHONE)
    render(<InstallLine />)
    expect(screen.getByText('To install, tap Share, then Add to Home Screen.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Install the app' })).toBeNull()
  })

  it('opened from the home screen: nothing', () => {
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(IPHONE)
    window.matchMedia = vi.fn().mockReturnValue({ matches: true }) as never
    const { container } = render(<InstallLine />)
    expect(container).toBeEmptyDOMElement()
  })

  it('Not now hides it, and it stays hidden when shown again', async () => {
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(IPHONE)
    const first = render(<InstallLine />)
    await userEvent.click(screen.getByRole('button', { name: 'Not now' }))
    expect(first.container).toBeEmptyDOMElement()
    first.unmount()
    const again = render(<InstallLine />)
    expect(again.container).toBeEmptyDOMElement()
  })
})
