import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { windowBackground } from './window-look'

const tokens = JSON.parse(readFileSync(join(__dirname, '..', '..', '..', 'docs', 'design', 'tokens.json'), 'utf8'))

describe('windowBackground', () => {
  it('is the ground colour of the system theme, so the window never opens white', () => {
    expect(windowBackground(false)).toBe(tokens.color.light.ground.value)
    expect(windowBackground(true)).toBe(tokens.color.dark.ground.value)
  })
})
