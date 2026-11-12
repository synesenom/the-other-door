// @vitest-environment jsdom
import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { named } from './AppName'

afterEach(cleanup)

describe('named', () => {
  it('sets every mention of the name, and keeps the words', () => {
    const { container } = render(<p>{named("Can't reach The other door. Is The other door on?")}</p>)
    expect(container.querySelectorAll('.app-name')).toHaveLength(2)
    expect(container).toHaveTextContent("Can't reach The other door. Is The other door on?")
  })

  it('leaves other messages as they are', () => {
    expect(named('Nothing to see')).toBe('Nothing to see')
    expect(named(null)).toBeNull()
  })
})
