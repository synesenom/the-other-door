import { describe, expect, it } from 'vitest'
import { answersFor } from '../test/world/build'
import { PERSONAS } from '../test/world/data/personas'

describe('answersFor', () => {
  it('gives the stand-in claude a skill-gap analysis and resources for some of its gaps', () => {
    const { gaps, resources } = answersFor(PERSONAS.mette) as {
      gaps: { gaps: { name: string }[] }
      resources: { resources: { gap: string; url: string }[] }
    }
    const names = gaps.gaps.map((g) => g.name)
    expect(resources.resources.length).toBeGreaterThan(0)
    expect(resources.resources.every((r) => names.includes(r.gap) && r.url.startsWith('https://'))).toBe(true)
    expect(resources.resources.length).toBeLessThan(names.length) // a gap with no resource is skipped
  })
})
