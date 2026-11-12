// @vitest-environment jsdom
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Splash } from './Splash'

afterEach(cleanup)

/** The markup inside an index.html's #root, whitespace between tags dropped. */
function rootMarkup(file: string): string {
  const html = readFileSync(file, 'utf8')
  const doc = new DOMParser().parseFromString(html, 'text/html')
  return (doc.getElementById('root')?.innerHTML ?? '').replace(/>\s+</g, '><').trim()
}

describe('Splash', () => {
  it('says the app is starting, with the logo and no words to read', () => {
    render(<Splash />)
    expect(screen.getByRole('status', { name: 'Starting The other door' })).toBeInTheDocument()
  })

  // The page shows the splash before any script runs, and React's first screen is the same splash,
  // so nothing blinks when it takes over.
  it.each([
    ['the desktop window', join(__dirname, 'index.html')],
    ['the phone app', join(__dirname, '..', 'web', 'index.html')],
  ])('%s has the same splash in its page before the script runs', (_name, file) => {
    const { container } = render(<Splash />)
    expect(rootMarkup(file)).toBe(container.innerHTML)
  })
})
