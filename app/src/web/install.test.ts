// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { captureInstallPrompt, dismiss, install, useInstallOffer } from './install'

const offer = () => renderHook(() => useInstallOffer()).result.current
const isIos = () => offer() === 'ios'

const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1'
const IPHONE_CHROME = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/124.0 Mobile/15E148 Safari/604.1'
const IPAD_AS_MAC = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15'
const ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36'

function setNav(ua: string, touch = 0, standalone?: boolean) {
  vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(ua)
  Object.defineProperty(navigator, 'maxTouchPoints', { value: touch, configurable: true })
  Object.defineProperty(navigator, 'standalone', { value: standalone, configurable: true })
}
function media(standalone: boolean) {
  window.matchMedia = vi.fn().mockReturnValue({ matches: standalone }) as never
}
function fakeEvent() {
  return Object.assign(new Event('beforeinstallprompt', { cancelable: true }), { prompt: vi.fn(async () => undefined) })
}

beforeEach(() => {
  localStorage.clear()
  media(false)
  setNav(ANDROID)
})
afterEach(() => {
  window.dispatchEvent(new Event('appinstalled')) // forgets a kept prompt
  vi.restoreAllMocks()
})

describe('the Share words', () => {
  // since iOS 16.4 every iPhone browser can add a page to the home screen from its Share sheet
  it('show in any iPhone browser, Safari or Chrome, and on an iPad that says Macintosh', () => {
    setNav(IPHONE)
    expect(isIos()).toBe(true)
    setNav(IPHONE_CHROME)
    expect(isIos()).toBe(true)
    setNav(IPAD_AS_MAC, 5)
    expect(isIos()).toBe(true)
  })
  it('do not show on a Mac or on Android', () => {
    setNav(IPAD_AS_MAC, 0)
    expect(isIos()).toBe(false)
    setNav(ANDROID)
    expect(isIos()).toBe(false)
  })
})

describe('opened from the home screen', () => {
  it('offers nothing, by the display mode or by iOS navigator.standalone', () => {
    setNav(IPHONE)
    expect(offer()).toBe('ios')
    media(true)
    expect(offer()).toBeNull()
    media(false)
    setNav(IPHONE, 5, true)
    expect(offer()).toBeNull()
  })
})

describe('the install prompt', () => {
  it('keeps the event (preventDefault), offers it, and prompts once on install()', async () => {
    const e = fakeEvent()
    captureInstallPrompt()
    const { result } = renderHook(() => useInstallOffer())
    act(() => void window.dispatchEvent(e))
    expect(e.defaultPrevented).toBe(true)
    expect(result.current).toBe('prompt')
    await act(() => install())
    expect(result.current).toBeNull()
    expect(e.prompt).toHaveBeenCalledTimes(1)
  })
  it('appinstalled clears the offer', () => {
    captureInstallPrompt()
    const { result } = renderHook(() => useInstallOffer())
    act(() => void window.dispatchEvent(fakeEvent()))
    expect(result.current).toBe('prompt')
    act(() => void window.dispatchEvent(new Event('appinstalled')))
    expect(result.current).toBeNull()
  })
  it('an iPhone gets the Share words; standalone and dismissed get nothing', () => {
    setNav(IPHONE)
    expect(offer()).toBe('ios')
    act(() => dismiss())
    expect(offer()).toBeNull()
    localStorage.clear()
    media(true)
    expect(offer()).toBeNull()
  })
  it('nothing when no event came and it is not iOS', () => {
    expect(offer()).toBeNull()
  })
})
