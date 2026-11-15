import { describe, expect, it } from 'vitest'
import { coversTitle, inventoryProblems, journeyRefs, testFileRefs, testTitles } from './inventory'
import { realInventory } from './inventory-files'

describe('testTitles', () => {
  it('reads the titles of test, test.skip and test.fixme, not of test.describe', () => {
    const src = [
      "test.describe('Area', () => {",
      "  test('opens it; then closes it', async () => {})",
      '  test.skip("a skipped one", async () => {})',
      "  test('it\\'s escaped', async () => {})",
      '})',
    ].join('\n')
    expect(testTitles(src)).toEqual(['opens it; then closes it', 'a skipped one', "it's escaped"])
  })
})

describe('journeyRefs', () => {
  it('takes what follows each ✓ up to the next one, its notes included', () => {
    expect(journeyRefs('- a branch — ✓ opens it (the notice); unit: `A.test.tsx`')).toEqual(['opens it (the notice); unit: `A.test.tsx`'])
    expect(journeyRefs('- x — ✓ one; ✓ two')).toEqual(['one', 'two'])
  })

  it('drops an expected-fail mark and skips the forms that name no test', () => {
    expect(journeyRefs('— ✓ (expected fail, BUG) the dialog starts on the checked status')).toEqual(['the dialog starts on the checked status'])
    expect(journeyRefs('— ✓ the same journey ("1 other request")')).toEqual([])
    expect(journeyRefs('— ✓ each below')).toEqual([])
    expect(journeyRefs('— ✓ (shown in finding-running)')).toEqual([])
    expect(journeyRefs('— ✓ `settings.journey.ts`')).toEqual([])
  })

  it('leaves the ✓ glyph of the UI alone', () => {
    expect(journeyRefs('**list "Why it fits"** (✓ marks) / marks: done ✓, failed ✗')).toEqual([])
  })
})

describe('coversTitle', () => {
  const titles = ['Prepare again asks first; Cancel and Escape leave it', 'lists the matches best first, each with its score', 'Interview: screening needs the kind picked first']

  it('accepts a whole title, with notes after it', () => {
    expect(coversTitle('Prepare again asks first; Cancel and Escape leave it (narrow)', titles)).toBe(true)
  })

  it('accepts a title shortened with …, and checks what follows the …', () => {
    expect(coversTitle('lists the matches best first… (2 decimals)', titles)).toBe(true)
    expect(coversTitle('Interview: … needs the kind picked first', titles)).toBe(true)
    expect(coversTitle('Interview: … needs nothing', titles)).toBe(false)
  })

  it('reads a … inside a note as the note’s, not as a shortened title', () => {
    expect(coversTitle('lists the matches best first, each with its score (Loading…: not tested)', titles)).toBe(true)
    expect(coversTitle('lists the matches best first… ("Stopping…" is not asserted)', titles)).toBe(true)
    expect(coversTitle('Applied through …; unit: `A.test.tsx`', titles)).toBe(false)
  })

  it('refuses a title cut short without …, or one no test has', () => {
    expect(coversTitle('Prepare again asks first', titles)).toBe(false)
    expect(coversTitle('a journey that was renamed', titles)).toBe(false)
  })
})

describe('testFileRefs', () => {
  it('names the test files a line points at, not the source files it describes', () => {
    const line = '- `Analytics.tsx` reads it — unit: `app/src/a/Analytics.test.tsx`, `B.test.ts`; preview: `preview.test.tsx`; `tests/core/test_usage_unit.py`; ✓ `cv.journey.ts`'
    expect(testFileRefs(line)).toEqual(['app/src/a/Analytics.test.tsx', 'B.test.ts', 'preview.test.tsx', 'tests/core/test_usage_unit.py', 'cv.journey.ts'])
  })
})

describe('inventoryProblems', () => {
  it('names the file, the line and what is missing', () => {
    const files = [{ name: 'jobs.md', text: '# Jobs\n- opens — ✓ opens it\n- shuts — ✓ gone away; unit: `Gone.test.tsx`' }]
    const problems = inventoryProblems(files, ['opens it'], (p) => p !== 'Gone.test.tsx')
    expect(problems).toEqual(['jobs.md:3: no journey test "gone away"', 'jobs.md:3: no test file Gone.test.tsx'])
  })
})

describe('the inventories in app/journeys/inventory', () => {
  it('name only journey tests and test files that exist', () => {
    const { files, titles, exists } = realInventory()
    expect(inventoryProblems(files, titles, exists)).toEqual([])
  })
})
