import { Fragment } from 'react'
import type { ReactNode } from 'react'
import { named } from './AppName'
import { TODO_WORD, todoOffsets } from './todos'

// A small Markdown reader for the CV preview and the skill-gap report: headings, paragraphs, lists,
// **bold**, *italic*, `code` and [links](https://…). It builds React elements, never HTML, so markup in
// the text stays text; a link opens in the browser through the main process, and only http(s) ones.

const INLINE = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g

/** With `onGap`, each `TODO` of the text is a marker; `next` keeps them numbered in the text's order. */
interface Gaps {
  next: number
  onGap: (n: number) => void
}

function words(text: string, gaps: Gaps | null): ReactNode {
  if (!gaps || todoOffsets(text).length === 0) return named(text)
  return text.split(TODO_WORD).map((part, i) => {
    const n = gaps.next
    if (i > 0) gaps.next += 1
    return (
      <Fragment key={i}>
        {i > 0 && (
          <button type="button" className="todo-mark" onClick={() => gaps.onGap(n)}>
            to fill in
          </button>
        )}
        {named(part)}
      </Fragment>
    )
  })
}

function inline(text: string, gaps: Gaps | null): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  for (const m of text.matchAll(INLINE)) {
    const token = m[0]
    const at = m.index ?? 0
    if (at > last) out.push(<Fragment key={`t${at}`}>{words(text.slice(last, at), gaps)}</Fragment>)
    const key = `${at}`
    if (token.startsWith('**')) out.push(<strong key={key}>{words(token.slice(2, -2), gaps)}</strong>)
    else if (token.startsWith('`')) out.push(<code key={key}>{gaps ? words(token.slice(1, -1), gaps) : token.slice(1, -1)}</code>)
    else if (token.startsWith('[')) {
      const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token)!
      const [, label, url] = link
      if (gaps) gaps.next += todoOffsets(token).length // no marker inside a link, but the count stays true to the text
      if (/^https?:\/\//i.test(url!)) {
        out.push(
          <button key={key} type="button" className="link-inline" onClick={() => void window.door.openExternal(url!)}>
            {label}
          </button>,
        )
      } else if (/^[a-z][a-z0-9+.-]*:/i.test(url!)) out.push(token)
      else out.push(label!) // a file of the repo, which can't open here: just its words
    } else out.push(<em key={key}>{words(token.slice(1, -1), gaps)}</em>)
    last = at + token.length
  }
  if (last < text.length) out.push(<Fragment key="end">{words(text.slice(last), gaps)}</Fragment>)
  return out
}

type Block = { kind: 'h'; level: number; text: string } | { kind: 'p'; text: string } | { kind: 'ul' | 'ol'; items: string[] }

function blocks(text: string): Block[] {
  const out: Block[] = []
  let para: string[] = []
  let list: Extract<Block, { kind: 'ul' | 'ol' }> | null = null
  const flush = () => {
    if (para.length) out.push({ kind: 'p', text: para.join(' ') })
    para = []
    list = null
  }
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    const heading = /^(#{1,6})\s+(.*)$/.exec(line)
    const bullet = /^[-*+]\s+(.*)$/.exec(line)
    const numbered = /^\d+[.)]\s+(.*)$/.exec(line)
    if (!line) flush()
    else if (heading) {
      flush()
      out.push({ kind: 'h', level: heading[1]!.length, text: heading[2]! })
    } else if (bullet || numbered) {
      const kind = bullet ? 'ul' : 'ol'
      if (para.length) flush()
      if (!list || list.kind !== kind) {
        list = { kind, items: [] }
        out.push(list)
      }
      list.items.push((bullet ?? numbered)![1]!)
    } else if (list && raw.startsWith('  ')) {
      list.items[list.items.length - 1] += ` ${line}` // a list item's continuation line
    } else {
      list = null
      para.push(line)
    }
  }
  flush()
  return out
}

/** Markdown as React elements; headings start one level below the page's (an h1 in the text is an h2). */
export function Markdown({ text, className, onGap, marked }: { text: string; className?: string; onGap?: (n: number) => void; marked?: string[] }) {
  const gaps = onGap ? { next: 0, onGap } : null
  // `marked`: list items and paragraphs whose text is one of these are tinted (what was just added to the CV)
  const isMarked = (t: string) => (marked?.some((m) => m.trim() === t.trim()) ? 'md-added' : undefined)
  return (
    <div className={className ? `markdown ${className}` : 'markdown'}>
      {blocks(text).map((b, i) => {
        if (b.kind === 'h') {
          const level = Math.min(b.level + 1, 6)
          const Tag = `h${level}` as 'h2'
          return (
            <Tag key={i} className={level <= 2 ? 'display-s' : 'md-heading'}>
              {inline(b.text, gaps)}
            </Tag>
          )
        }
        if (b.kind === 'p') return <p key={i} className={isMarked(b.text)}>{inline(b.text, gaps)}</p>
        const List = b.kind
        return (
          <List key={i}>
            {b.items.map((item, j) => (
              <li key={j} className={isMarked(item)}>{inline(item, gaps)}</li>
            ))}
          </List>
        )
      })}
    </div>
  )
}
