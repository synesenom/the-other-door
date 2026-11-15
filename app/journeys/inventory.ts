// The offline check of the journey checklists (#122): every `✓ <title>` in `inventory/*.md` names a journey test
// that exists, and every test file a line points at (`unit: …`, `preview: …`, a `*.journey.ts`) is on disk. Pure:
// the files, the titles and the file lookup come from the caller (`inventory-files.ts` reads the real ones).

/** The titles of `test(…)`, `test.skip(…)`, `test.fixme(…)` and `test.only(…)` calls; not `test.describe`'s. */
export function testTitles(source: string): string[] {
  const titles: string[] = []
  for (const m of source.matchAll(/\btest(?:\.(?:skip|fixme|only))?\(\s*(['"`])((?:\\.|(?!\1).)*)\1/g)) {
    titles.push(m[2]!.replace(/\\(.)/g, '$1'))
  }
  return titles
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

/** What a reference says before its notes, for a message. */
const label = (ref: string): string => ref.split(/;\s*(?:unit|preview):|\s—\s/)[0]!.replace(/[;\s]+$/, '')

/**
 * A reference covers a title when it starts with the whole title (notes may follow), or shortens it with `…`: the text
 * before the first `…` starts the title, each part between `…`s follows in order, and the words after the last `…`
 * (up to a note) are in the rest of the title.
 */
export function coversTitle(ref: string, titles: string[]): boolean {
  if (titles.some((t) => ref.startsWith(t))) return true
  // the shortened title ends where its notes begin; a … inside a note ("Stopping…") is the note's
  const head = ref.split(/\s\(|;\s|\s\|/)[0]!
  if (!head.includes('…')) return false
  const parts = head.split('…')
  const tail = parts.pop()!.split(/\s\(|;|\)|\s—\s|\s\|/)[0]!.trim()
  return titles.some((title) => {
    if (!title.startsWith(parts[0]!)) return false
    let at = parts[0]!.length
    for (const part of parts.slice(1)) {
      const found = title.indexOf(part.trim(), at)
      if (found < 0) return false
      at = found + part.trim().length
    }
    return !tail || title.indexOf(tail, at) >= 0
  })
}

/** The test files a line points at: backquoted `*.test.ts(x)`, `*.journey.ts` and Python `test_*.py` paths. */
export function testFileRefs(line: string): string[] {
  return [...line.matchAll(/`([\w./-]+)`/g)]
    .map((m) => m[1]!)
    .filter((p) => /\.test\.tsx?$|\.journey\.ts$|(?:^|\/)test_\w+\.py$/.test(p))
}

/** Every reference in the inventories that names no journey test or no file on disk, as `<file>:<line>: <what>`. */
export function inventoryProblems(files: { name: string; text: string }[], titles: string[], exists: (path: string) => boolean): string[] {
  const problems: string[] = []
  for (const { name, text } of files) {
    text.split('\n').forEach((line, i) => {
      for (const ref of journeyRefs(line)) {
        if (!coversTitle(ref, titles)) problems.push(`${name}:${i + 1}: no journey test "${label(ref)}"`)
      }
      for (const path of testFileRefs(line)) {
        if (!exists(path)) problems.push(`${name}:${i + 1}: no test file ${path}`)
      }
    })
  }
  return problems
}
