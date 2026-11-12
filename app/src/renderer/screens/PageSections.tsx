import { useEffect, useRef, useState } from 'react'

/** A whole other view of the screen listed after the sections (Profile's CV and Stories): opened, not scrolled to. */
export interface PagePart {
  label: string
  current: boolean
  onOpen: () => void
}

/**
 * The parts of a one-column screen, listed beside it (Profile, Settings): where you are, and a jump to any
 * of them. `id` is the element each part's heading has; a part folded in a closed <details> is unfolded.
 * `elsewhere`: the sections are not on screen (another view is), so none is marked and a click hands its id
 * over; `parts` follow the sections.
 */
export function PageSections({ sections, parts = [], elsewhere }: { sections: { id: string; label: string }[]; parts?: PagePart[]; elsewhere?: (id: string) => void }) {
  const [here, setHere] = useState(sections[0]?.id)
  // a part jumped to stays marked while the jump scrolls, even one too short to reach the line
  const jumped = useRef<string | null>(null)
  const ids = sections.map((s) => s.id).join()
  useEffect(() => {
    const pane = document.querySelector('.main')
    if (!pane || elsewhere) return
    // the last part whose heading has passed a line that moves down the pane as it scrolls: a third of the
    // way down at the top, its foot at the end, so the parts near the end (too short to scroll their
    // heading up) each have their turn
    const onScroll = () => {
      if (jumped.current) return
      const room = pane.scrollHeight - pane.clientHeight
      const progress = room > 0 ? Math.min(1, pane.scrollTop / room) : 0
      const line = pane.getBoundingClientRect().top + pane.clientHeight * (1 / 3 + (2 / 3) * progress)
      let at = sections[0]?.id
      for (const s of sections) {
        const h = document.getElementById(s.id)
        if (h && h.getBoundingClientRect().top <= line) at = s.id
      }
      setHere(at)
    }
    const onScrollEnd = () => {
      jumped.current = null
    }
    onScroll()
    pane.addEventListener('scroll', onScroll, { passive: true })
    pane.addEventListener('scrollend', onScrollEnd)
    return () => {
      pane.removeEventListener('scroll', onScroll)
      pane.removeEventListener('scrollend', onScrollEnd)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids, Boolean(elsewhere)])
  return (
    <nav className="page-aside" aria-label="Sections">
      <ul>
        {sections.map((s) => (
          <li key={s.id}>
            <a
              href={`#${s.id}`}
              aria-current={!elsewhere && s.id === here ? 'location' : undefined}
              onClick={(e) => {
                e.preventDefault()
                if (elsewhere) {
                  // marked now and kept while the other view's scroll to it runs, as a jump on the page is
                  jumped.current = s.id
                  setHere(s.id)
                  return elsewhere(s.id)
                }
                const el = document.getElementById(s.id)
                const folded = el?.closest('details')
                if (folded && !folded.open) folded.open = true
                jumped.current = s.id
                setHere(s.id)
                el?.scrollIntoView?.({ block: 'start', behavior: 'smooth' })
              }}
            >
              {s.label}
            </a>
          </li>
        ))}
        {parts.map((p, i) => (
          <li key={p.label} className={i === 0 && sections.length > 0 ? 'page-aside-parts' : undefined}>
            <a
              href={`#${p.label}`}
              aria-current={p.current ? 'page' : undefined}
              onClick={(e) => {
                e.preventDefault()
                p.onOpen()
              }}
            >
              {p.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  )
}
