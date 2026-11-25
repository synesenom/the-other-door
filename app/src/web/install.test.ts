// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { captureInstallPrompt, dismiss, dismissed, install, isIosSafari, isStandalone, offer, resetInstall, subscribe } from './install'

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
  resetInstall()
  media(false)
  setNav(ANDROID)
})
afterEach(() => vi.restoreAllMocks())

describe('isIosSafari', () => {
  it('is true for iPhone Safari and for an iPad that says Macintosh', () => {
    setNav(IPHONE)
    expect(isIosSafari()).toBe(true)
    setNav(IPAD_AS_MAC, 5)
    expect(isIosSafari()).toBe(true)
  })
  it('is false for a Mac, another iOS browser and Android', () => {
    setNav(IPAD_AS_MAC, 0)
    expect(isIosSafari()).toBe(false)
    setNav(IPHONE_CHROME)
    expect(isIosSafari()).toBe(false)
    setNav(ANDROID)
    expect(isIosSafari()).toBe(false)
  })
})

describe('isStandalone', () => {
  it('reads the display mode and iOS navigator.standalone', () => {
    expect(isStandalone()).toBe(false)
    media(true)
    expect(isStandalone()).toBe(true)
    media(false)
    setNav(IPHONE, 5, true)
    expect(isStandalone()).toBe(true)
  })
})

describe('the install prompt', () => {
  it('keeps the event (preventDefault), offers it, and prompts once on install()', async () => {
    const seen = vi.fn()
    subscribe(seen)
    const e = fakeEvent()
    captureInstallPrompt()
    window.dispatchEvent(e)
    expect(e.defaultPrevented).toBe(true)
    expect(seen).toHaveBeenCalled()
    expect(offer()).toBe('prompt')
    await install()
    expect(e.prompt).toHaveBeenCalledTimes(1)
  })
  it('appinstalled clears the offer', () => {
    captureInstallPrompt()
    window.dispatchEvent(fakeEvent())
    window.dispatchEvent(new Event('appinstalled'))
    expect(offer()).toBeNull()
  })
  it('iOS Safari gets the Share words; standalone and dismissed get nothing', () => {
    setNav(IPHONE)
    expect(offer()).toBe('ios')
    dismiss()
    expect(dismissed()).toBe(true)
    expect(offer()).toBeNull()
    localStorage.clear()
    media(true)
    expect(offer()).toBeNull()
  })
  it('nothing when no event came and it is not iOS', () => {
    expect(offer()).toBeNull()
  })
})
