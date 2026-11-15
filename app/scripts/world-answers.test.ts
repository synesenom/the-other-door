import { describe, expect, it } from 'vitest'
import { answersFor } from '../test/world/build'
import { PERSONAS } from '../test/world/data/personas'

describe('answersFor', () => {
  it('gives the stand-in claude a skill-gap report that skill_gaps counts and cites', () => {
    const { gaps } = answersFor(PERSONAS.mette) as { gaps: string }
    expect(gaps).toMatch(/^### \d+\./m)
    expect(gaps).toContain('## Skipped gaps')
  })
})
