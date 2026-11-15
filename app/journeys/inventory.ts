// The offline check of the journey checklists (#122): every `✓ <title>` in `inventory/*.md` names a journey test
// that exists and runs, each title on a line has its own ✓, each journey is named whole at least once, and every
// test file a line points at (`unit: …`, `preview: …`, a `*.journey.ts`) is on disk. Pure: the files, the tests and
// the file lookup come from the caller (`inventory-files.ts` reads the real ones).

export interface JourneyTest {
  title: string
  /** `test.skip`, `test.fixme`, or inside a `test.describe.skip` / `.fixme` block: it covers nothing. */
  skipped: boolean
}

/** The `test(…)` calls of a journey file (not `test.describe`'s titles), each marked skipped or not. */
export function journeyTests(source: string): JourneyTest[] {
  const tests: JourneyTest[] = []
  // a skipped describe block runs from its line to the first later line at its indent or less
  const lines = source.split('\n')
  const skippedLines = new Set<number>()
  lines.forEach((line, i) => {
    const m = /^(\s*)test\.describe\.(?:skip|fixme)\(/.exec(line)
    if (!m) return
    const indent = m[1]!.length
    for (let j = i + 1; j < lines.length; j++) {
      const l = lines[j]!
      if (l.trim() && l.length - l.trimStart().length <= indent) break
      skippedLines.add(j)
    }
  })
  let offset = 0
  const lineAt = (index: number): number => {
    while (offset < lines.length && index > lines.slice(0, offset + 1).join('\n').length) offset++
    return offset
  }
  for (const m of source.matchAll(/\btest(?:\.(skip|fixme|only))?\(\s*(['"`])((?:\\.|(?!\2).)*)\2/g)) {
    const skipped = m[1] === 'skip' || m[1] === 'fixme' || skippedLines.has(lineAt(m.index!))
    tests.push({ title: m[3]!.replace(/\\(.)/g, '$1'), skipped })
  }
  return tests
}

/** Forms after a ✓ that name no test: a pointer to the line before, one to the lines after, a file (see `testFileRefs`). */
const NOT_A_TITLE = /^(?:the same journey|each below)\b|^`|^[\w/-]+\.journey\.ts\b/

/**
 * What follows each ✓ that marks a journey covering the branch, up to the next ✓: the title and any notes after it.
 * The ✓ the screens themselves show (`(✓ marks)`, `done ✓,`) is not a mark; a leading `(expected fail…)` is dropped;
 * a ✓ followed only by a note in parentheses names no test.
 */
export function journeyRefs(line: string): string[] {
  const refs: string[] = []
  const parts = line.split('✓')
  for (let i = 1; i < parts.length; i++) {
    const before = parts[i - 1]!
    const after = parts[i]!
    if (before.endsWith('(') || /^\s*[,)]/.test(after) || /^\s*marks\b/.test(after)) continue
    let ref = after.trim().replace(/[;\s]+$/, '')
    ref = ref.replace(/^\((?:expected fail|test\.fail)[^)]*\)\s*/i, '')
    if (!ref || ref.startsWith('(') || NOT_A_TITLE.test(ref)) continue
    refs.push(ref)
  }
  return refs
}

/** A whole title ends the reference or is followed by a note: `;`, ` (`, ` —`, ` |`, `)`, `…` or `:`. */
const BOUNDARY = /^(?:$|;|\s\(|\s—|\s\||\)|…|:)/
/** A shortened title ends where its notes begin; a … inside a note ("Stopping…") is the note's. */
const headOf = (ref: string): string => ref.split(/\s\(|;\s|\s\||\s—\s/)[0]!
/** What a reference says before its notes, for a message. */
const label = (ref: string): string => headOf(ref).replace(/[;\s]+$/, '')

/** The titles a `…`-shortened head fits: it starts the title, each part between `…`s follows in order. */
function shortenedMatches(head: string, tests: JourneyTest[]): JourneyTest[] {
  const parts = head.split('…').map((p) => p.trim())
  return tests.filter(({ title }) => {
    if (!title.startsWith(parts[0]!)) return false
    let at = parts[0]!.length
    for (const part of parts.slice(1)) {
      if (!part) continue
      const found = title.indexOf(part, at)
      if (found < 0) return false
      at = found + part.length
    }
    return true
  })
}

/**
 * The journey test a reference names: the longest whole title it starts with (up to a boundary), or else the one title
 * its `…`-shortened head fits (the text before the first `…` at least 3 words or 20 characters). A skipped test covers
 * nothing.
 */
export function resolveRef(ref: string, tests: JourneyTest[]): { title?: string; whole?: boolean; problem?: string } {
  const whole = tests
    .filter((t) => ref.startsWith(t.title) && BOUNDARY.test(ref.slice(t.title.length)))
    .sort((a, b) => b.title.length - a.title.length)[0]
  const head = headOf(ref)
  let found: JourneyTest | undefined = whole
  if (!found) {
    if (!head.includes('…')) return { problem: `no journey test "${label(ref)}"` }
    const start = head.split('…')[0]!.trim()
    if (start.length < 20 && start.split(/\s+/).filter(Boolean).length < 3) return { problem: `"${label(ref)}" is too short to name a journey test` }
    const matches = shortenedMatches(head, tests)
    if (matches.length === 0) return { problem: `no journey test "${label(ref)}"` }
    if (matches.length > 1) return { problem: `"${label(ref)}" fits ${matches.length} journey tests; say which` }
    found = matches[0]
  }
  if (found!.skipped) return { problem: `"${found!.title}" is a skipped journey: it covers nothing` }
  return { title: found!.title, whole: !!whole }
}

/** A `; ` segment after a ✓ title that is itself a journey title (whole or shortened) but has no ✓. */
function untickedTitles(ref: string, title: string, tests: JourneyTest[]): string[] {
  const rest = ref.slice(ref.startsWith(title) ? title.length : headOf(ref).length)
  const out: string[] = []
  for (const segment of rest.split(/;\s+/).slice(1)) {
    const text = segment.trim()
    if (!text || /^(?:unit|preview|not\b)/.test(text)) continue
    const r = resolveRef(text, tests)
    if (r.title) out.push(r.title)
  }
  return out
}

/** The test files a line points at, backquoted or not: `*.test.ts(x)`, `*.journey.ts` and Python `test_*.py` paths. */
export function testFileRefs(line: string): string[] {
  const refs = [...line.matchAll(/(?<![\w./*-])([\w./-]*?(?:\.test\.tsx?|\.journey\.ts|(?:^|\/|\b)test_\w+\.py))(?![\w.])/g)].map((m) => m[1]!)
  // a glob (`*.journey.ts`, `src/**/*.test.tsx`) names no file
  return [...new Set(refs)].filter((p) => !/(?:^|\/)\./.test(p))
}

/** Every reference in the inventories that names no running journey test or no file on disk, as `<file>:<line>: <what>`. */
export function inventoryProblems(files: { name: string; text: string }[], tests: JourneyTest[], exists: (path: string) => boolean): string[] {
  const problems: string[] = []
  const namedWhole = new Set<string>()
  const shortenedAt = new Map<string, string>()
  for (const { name, text } of files) {
    text.split('\n').forEach((line, i) => {
      const at = `${name}:${i + 1}`
      for (const ref of journeyRefs(line)) {
        const r = resolveRef(ref, tests)
        if (r.problem) {
          problems.push(`${at}: ${r.problem}`)
          continue
        }
        if (r.whole) namedWhole.add(r.title!)
        else if (!shortenedAt.has(r.title!)) shortenedAt.set(r.title!, at)
        for (const t of untickedTitles(ref, r.title!, tests)) problems.push(`${at}: "${t}" is a journey title without its ✓`)
      }
      for (const path of testFileRefs(line)) {
        if (!exists(path)) problems.push(`${at}: no test file ${path}`)
      }
    })
  }
  for (const [title, at] of shortenedAt) {
    if (!namedWhole.has(title)) problems.push(`${at}: "${title}" is only named shortened with …; name it whole once`)
  }
  return problems
}
