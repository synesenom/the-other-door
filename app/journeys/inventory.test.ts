import { describe, expect, it } from 'vitest'
import { inventoryProblems, journeyRefs, journeyTests, resolveRef, testFileRefs, type JourneyTest } from './inventory'
import { realInventory } from './inventory-files'

const run = (...titles: string[]): JourneyTest[] => titles.map((title) => ({ title, skipped: false }))

describe('journeyTests', () => {
  it('reads the titles of test, test.skip and test.fixme, not of test.describe', () => {
    const src = [
      "test.describe('Area', () => {",
      "  test('opens it; then closes it', async () => {})",
      '  test.skip("a skipped one", async () => {})',
      "  test('it\\'s escaped', async () => {})",
      '})',
    ].join('\n')
    expect(journeyTests(src)).toEqual([
      { title: 'opens it; then closes it', skipped: false },
      { title: 'a skipped one', skipped: true },
      { title: "it's escaped", skipped: false },
    ])
  })

  it('marks every test inside a test.describe.skip block as skipped, and none after it', () => {
    const src = [
      "test.describe.skip('Your phone', () => {",
      "  test('pairs it', async () => {",
      '  })',
      '})',
      "test('after it', async () => {})",
    ].join('\n')
    expect(journeyTests(src)).toEqual([
      { title: 'pairs it', skipped: true },
      { title: 'after it', skipped: false },
    ])
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

describe('resolveRef', () => {
  const tests = run(
    'Prepare again asks first; Cancel and Escape leave it',
    'Prepared moves the job to Applications',
    'Prepared moves the job to Applications and keeps the letter',
    'lists the matches best first, each with its score',
    'Interview: screening needs the kind picked first',
    'a wrong code fails the sign-in',
    'a wrong code fails with claude’s reason',
  )

  it('accepts a whole title, alone or followed by a note', () => {
    for (const ref of ['Prepare again asks first; Cancel and Escape leave it', 'Prepare again asks first; Cancel and Escape leave it (narrow)', 'Prepared moves the job to Applications; unit: `A.test.tsx`', 'Prepared moves the job to Applications — not the phone', 'Prepared moves the job to Applications |', 'Prepared moves the job to Applications: the board', 'Prepared moves the job to Applications)'])
      expect(resolveRef(ref, tests), ref).toMatchObject({ title: expect.any(String), whole: true })
  })

  it('refuses a title that runs on past a whole one without a boundary: a shortened rename, a typo after a sibling', () => {
    expect(resolveRef('Prepared moves the job to Applications and bcak', tests).problem).toMatch(/no journey test/)
    expect(resolveRef('lists the matches best first, each with', tests).problem).toMatch(/no journey test/)
  })

  it('takes the longest whole title that fits', () => {
    expect(resolveRef('Prepared moves the job to Applications and keeps the letter (narrow)', tests).title).toBe('Prepared moves the job to Applications and keeps the letter')
  })

  it('accepts a title shortened with …, and checks what follows the …', () => {
    expect(resolveRef('lists the matches best first… (2 decimals)', tests)).toMatchObject({ title: 'lists the matches best first, each with its score', whole: false })
    expect(resolveRef('Interview: screening … the kind picked first', tests).title).toBe('Interview: screening needs the kind picked first')
    expect(resolveRef('Interview: screening … needs nothing', tests).problem).toMatch(/no journey test/)
  })

  it('reads a … inside a note as the note’s', () => {
    expect(resolveRef('lists the matches best first, each with its score (Loading…: not tested)', tests).whole).toBe(true)
    expect(resolveRef('lists the matches best first… ("Stopping…" is not asserted)', tests).title).toBe('lists the matches best first, each with its score')
  })

  it('refuses a … too short to name a test, and one that fits several', () => {
    expect(resolveRef('…', tests).problem).toMatch(/too short/)
    expect(resolveRef('lists…', tests).problem).toMatch(/too short/)
    expect(resolveRef('a wrong code fails…', tests).problem).toMatch(/2 journey tests/)
    expect(resolveRef('a wrong code fails the…', tests).title).toBe('a wrong code fails the sign-in')
  })

  it('refuses a skipped journey: it covers nothing', () => {
    const skipped = [{ title: 'pairs the phone', skipped: true }]
    expect(resolveRef('pairs the phone', skipped).problem).toMatch(/skipped/)
  })
})

describe('testFileRefs', () => {
  it('names the test files a line points at, backquoted or not, not the source files it describes', () => {
    const line = '- `Analytics.tsx` reads it — unit: `app/src/a/Analytics.test.tsx`, `B.test.ts`; preview: preview.test.tsx; tests/core/test_usage_unit.py; ✓ `cv.journey.ts` (report.journey.ts)'
    expect(testFileRefs(line)).toEqual(['app/src/a/Analytics.test.tsx', 'B.test.ts', 'preview.test.tsx', 'tests/core/test_usage_unit.py', 'cv.journey.ts', 'report.journey.ts'])
  })

  it('reads a glob as no file', () => {
    expect(testFileRefs('each `*.journey.ts` and `src/**/*.test.tsx`')).toEqual([])
  })
})

describe('inventoryProblems', () => {
  it('names the file, the line and what is missing', () => {
    const files = [{ name: 'jobs.md', text: '# Jobs\n- opens — ✓ opens it\n- shuts — ✓ gone away; unit: `Gone.test.tsx`' }]
    expect(inventoryProblems(files, run('opens it'), (p) => p !== 'Gone.test.tsx')).toEqual(['jobs.md:3: no journey test "gone away"', 'jobs.md:3: no test file Gone.test.tsx'])
  })

  it('wants a ✓ before each journey title on a line', () => {
    const files = [{ name: 'a.md', text: '- x — ✓ opens it; closes it again; unit: `A.test.tsx`' }]
    expect(inventoryProblems(files, run('opens it', 'closes it again'), () => true)).toEqual(['a.md:1: "closes it again" is a journey title without its ✓'])
  })

  it('wants each journey named whole at least once, not only shortened with …', () => {
    const files = [{ name: 'a.md', text: '- x — ✓ opens the posting full…\n- y — ✓ opens the posting full…' }]
    expect(inventoryProblems(files, run('opens the posting full width'), () => true)).toEqual(['a.md:1: "opens the posting full width" is only named shortened with …; name it whole once'])
  })
})

describe('the inventories in app/journeys/inventory', () => {
  it('name only journey tests and test files that exist', () => {
    const { files, tests, exists } = realInventory()
    expect(inventoryProblems(files, tests, exists)).toEqual([])
  })
})
