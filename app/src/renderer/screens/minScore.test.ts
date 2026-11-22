import { describe, expect, it } from 'vitest'
import fields from './profile-form/fields.json'
import { runAccount } from './Finding'
import { emptyText } from './Matches'
import { MIN_SCORE_NAME, minScoreValue } from './minScore'

describe('the minimum score has one name and the score format', () => {
  it('is named as Profile names it', () => {
    expect(MIN_SCORE_NAME).toBe(fields.fields.find((f) => f.key === 'min_score')!.label)
  })

  it('reads the value the way scores are, never as a percentage', () => {
    expect(minScoreValue(0.65)).toBe('0.65 or better')
  })

  it('the run summary and the empty Matches list use both', () => {
    const line = runAccount({ match: { scored: 40, min_score: 0.65, above_threshold: 0 }, search: { sites: [] } } as never)
    expect(line).toContain(`${MIN_SCORE_NAME}: 0.65 or better`)
    expect(emptyText(5, 0.65, null, false)).toContain(`${MIN_SCORE_NAME}: 0.65 or better`)
    expect(line).not.toContain('%')
  })
})
