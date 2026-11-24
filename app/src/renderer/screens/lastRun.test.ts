import { describe, expect, it } from 'vitest'
import { runFreshness } from './lastRun'

const NOW = new Date('2026-11-24T12:00:00Z')
const ago = (h: number) => new Date(NOW.getTime() - h * 3_600_000).toISOString()

describe('runFreshness', () => {
  it('says when the last run was, in words, and nothing to warn of while it is fresh', () => {
    expect(runFreshness(ago(0.2), NOW)).toEqual({ last: 'Last run just now', stale: null })
    expect(runFreshness(ago(2), NOW)).toEqual({ last: 'Last run 2 h ago', stale: null })
    expect(runFreshness(ago(30), NOW)).toEqual({ last: 'Last run yesterday', stale: null })
  })

  it('warns once two days passed with no run, counting the days', () => {
    expect(runFreshness(ago(48), NOW)).toEqual({ last: 'Last run 2 days ago', stale: 'No run in 2 days' })
    expect(runFreshness(ago(24 * 9 + 3), NOW)).toEqual({ last: 'Last run 9 days ago', stale: 'No run in 9 days' })
  })

  it('warns when there never was a run, and reads a date it cannot parse as none', () => {
    expect(runFreshness(null, NOW)).toEqual({ last: null, stale: 'Not run yet' })
    expect(runFreshness('not a date', NOW)).toEqual({ last: null, stale: 'Not run yet' })
  })
})
