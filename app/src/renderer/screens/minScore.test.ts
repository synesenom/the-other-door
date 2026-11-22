import { describe, expect, it } from 'vitest'
import { runAccount } from './Finding'
import { emptyText } from './Matches'
import { minScoreSetting, minScoreValue } from './minScore'

describe('the minimum score has one name and the score format', () => {
  it('reads the value the way scores are, never as a percentage', () => {
    expect(minScoreValue(0.65)).toBe('0.65 or better')
  })

  it('names the choice Profile shows, or the value set by hand', () => {
    expect(minScoreSetting(0.65)).toBe('Match fit: Balanced')
    expect(minScoreSetting(0.7)).toBe('Match fit: Your own (0.70)')
  })

  it('the run summary and the empty Matches list say the value as a score', () => {
    const line = runAccount({ match: { scored: 40, min_score: 0.65, above_threshold: 0 }, search: { sites: [] } } as never)
    expect(line).toMatch(/none scored 0.65 or better$/)
    expect(emptyText(5, 0.65, null, false)).toBe('Nothing has scored 0.65 or better yet.')
    expect(line).not.toContain('%')
  })
})
