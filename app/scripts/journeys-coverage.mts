// What of the renderer the journeys exercised: `JOURNEYS_COVERAGE=1 npm run test:journeys` leaves one
// V8 block-coverage file per test in journeys-coverage/; this merges them over the built renderer bundle
// (unminified, one `// src/renderer/...` marker per module) and attributes each byte to its source file.
// Writes journeys-coverage/report.md (per file: share of code run, and every block no journey reached,
// with its code), prints the table, and exits 1 when the total is under --min (default 0).
//   tsx scripts/journeys-coverage.mts [--min 95]
import { readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

interface Range {
  startOffset: number
  endOffset: number
  count: number
}
interface Entry {
  url: string
  source: string
  functions: { functionName: string; ranges: Range[] }[]
}

const dir = resolve(import.meta.dirname, '..', 'journeys-coverage')
const min = Number(process.argv[process.argv.indexOf('--min') + 1] || 0)
const files = readdirSync(dir).filter((f) => f.endsWith('.json'))
if (files.length === 0) {
  console.error('no coverage files: run the journeys with JOURNEYS_COVERAGE=1 first')
  process.exit(1)
}

let source = ''
let covered: Uint8Array | null = null
for (const f of files) {
  for (const e of JSON.parse(readFileSync(join(dir, f), 'utf8')) as Entry[]) {
    if (!source) source = e.source
    if (e.source !== source) continue // another build: skip rather than mix offsets
    covered ??= new Uint8Array(source.length)
    // Innermost range wins: paint outer ranges first. A byte no range claims did not run: a window
    // reloaded in a test leaves an entry that reports only the few functions run after the reload.
    const mine = new Int8Array(source.length)
    const ranges = e.functions.flatMap((fn) => fn.ranges).sort((a, b) => b.endOffset - b.startOffset - (a.endOffset - a.startOffset))
    for (const r of ranges) mine.fill(r.count > 0 ? 1 : 0, r.startOffset, r.endOffset)
    for (let i = 0; i < mine.length; i++) if (mine[i]) covered[i] = 1
  }
}
if (!covered) throw new Error('no renderer bundle in the coverage files')

// Each module's span in the bundle, from its marker to the next marker.
const marker = /^\/\/ (\S+)$/gm
const spans: { file: string; start: number; end: number }[] = []
for (let m = marker.exec(source), prev: { file: string; start: number } | null = null; ; m = marker.exec(source)) {
  if (prev) spans.push({ ...prev, end: m ? m.index : source.length })
  if (!m) break
  prev = { file: m[1], start: m.index + m[0].length }
}
// A module the bundler folded in without a marker of its own (Matches.tsx, which App also imports a
// constant from) starts at its first top-level declaration: split the span it sits in there.
const renderer = resolve(import.meta.dirname, '..', 'src', 'renderer')
for (const file of readdirSync(renderer, { recursive: true, encoding: 'utf8' })) {
  if (!/\.tsx?$/.test(file) || /\.test\.|\.d\.ts$|testing\.tsx?$/.test(file)) continue
  const name = `src/renderer/${file}`
  if (spans.some((s) => s.file === name)) continue
  const text = readFileSync(join(renderer, file), 'utf8')
  const first = (/^export (?:async )?function (\w+)/m.exec(text) ?? /^export (?:const|let|class) (\w+)/m.exec(text))?.[1]
  const at = first ? new RegExp(`^(?:async )?(?:function|const|let|var|class) ${first}\\b`, 'm').exec(source) : null
  const host = at && spans.find((s) => s.start <= at.index && at.index < s.end)
  if (!at || !host) continue
  spans.push({ file: name, start: at.index, end: host.end })
  host.end = at.index
}
const lineAt = (offset: number) => source.slice(0, offset).split('\n').length

interface FileReport {
  file: string
  total: number
  run: number
  gaps: { from: number; to: number; code: string }[]
}
const reports: FileReport[] = []
for (const s of spans.filter((x) => x.file.startsWith('src/renderer/'))) {
  const r: FileReport = { file: s.file, total: 0, run: 0, gaps: [] }
  let gapStart = -1
  // Count code characters only: not whitespace, not comment lines.
  const text = source.slice(s.start, s.end)
  const isComment = new Uint8Array(text.length)
  for (const c of text.matchAll(/^\s*(\/\/.*|\/\*[\s\S]*?\*\/)/gm)) isComment.fill(1, c.index!, c.index! + c[0].length)
  for (let i = s.start; i < s.end; i++) {
    const ch = source[i]
    const code = !/\s/.test(ch) && !isComment[i - s.start]
    if (code) {
      r.total += 1
      if (covered[i]) r.run += 1
    }
    if (code && !covered[i] && gapStart < 0) gapStart = i
    if (gapStart >= 0 && (covered[i] || i === s.end - 1) && code) {
      const snippet = source.slice(gapStart, i).trim()
      if (snippet.replace(/[\s{}();,]/g, '').length > 2) r.gaps.push({ from: lineAt(gapStart), to: lineAt(i), code: snippet.slice(0, 400) })
      gapStart = -1
    }
  }
  reports.push(r)
}

const pct = (r: { run: number; total: number }) => (r.total ? (100 * r.run) / r.total : 100)
const total = reports.reduce((a, r) => ({ run: a.run + r.run, total: a.total + r.total }), { run: 0, total: 0 })
reports.sort((a, b) => pct(a) - pct(b))
const table = reports.map((r) => `| ${r.file.replace('src/renderer/', '')} | ${pct(r).toFixed(1)}% | ${r.gaps.length} |`)
const md = [
  `# Journeys: renderer coverage`,
  '',
  `${files.length} tests, ${pct(total).toFixed(1)}% of the renderer's code run.`,
  '',
  '| File | Run | Blocks never run |',
  '|---|---|---|',
  ...table,
  '',
  ...reports
    .filter((r) => r.gaps.length)
    .flatMap((r) => [`## ${r.file}`, '', ...r.gaps.map((g) => `- bundle lines ${g.from}–${g.to}:\n\n  \`\`\`js\n  ${g.code.replace(/\n/g, '\n  ')}\n  \`\`\``), '']),
].join('\n')
writeFileSync(join(dir, 'report.md'), md)
console.log(['| File | Run | Gaps |', ...table].join('\n'))
console.log(`\nTotal: ${pct(total).toFixed(1)}% (${files.length} tests). Details: journeys-coverage/report.md`)
if (pct(total) < min) {
  console.error(`under the minimum of ${min}%`)
  process.exit(1)
}
