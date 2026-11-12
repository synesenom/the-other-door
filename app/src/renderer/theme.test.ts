// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { applyTheme, readTheme, saveTheme } from './theme'

afterEach(() => {
  localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
  vi.restoreAllMocks()
})

describe('theme', () => {
  it('follows the system until chosen', () => {
    expect(readTheme()).toBe('system')
  })

  it('remembers a choice and sets it on the page; system takes it off', () => {
    saveTheme('dark')
    expect(readTheme()).toBe('dark')
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
    saveTheme('system')
    expect(readTheme()).toBe('system')
    expect(document.documentElement).not.toHaveAttribute('data-theme')
  })

  it('an odd stored value is the system one', () => {
    localStorage.setItem('door.theme', 'purple')
    expect(readTheme()).toBe('system')
  })

  it('a storage that throws changes nothing but the page', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(readTheme()).toBe('system')
    saveTheme('light')
    expect(document.documentElement).toHaveAttribute('data-theme', 'light')
  })

  it('applyTheme sets what it is given', () => {
    applyTheme('light')
    expect(document.documentElement).toHaveAttribute('data-theme', 'light')
  })
})
