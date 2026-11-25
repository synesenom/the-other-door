import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

/**
 * Words that would crowd the page, behind an info icon: open while the pointer is on the icon or the words,
 * or while the icon has the keyboard's focus; Escape closes them. A moment's grace after the pointer leaves,
 * so a diagonal way from the icon to the words does not close them.
 */
const GRACE_MS = 200

/** The top edge the words must stay under: the window's, or that of a box around them that cuts off what overflows. */
function clipTop(el: HTMLElement): number {
  let top = 0
  for (let box = el.parentElement; box; box = box.parentElement) {
    if (getComputedStyle(box).overflowY !== 'visible') top = Math.max(top, box.getBoundingClientRect().top)
  }
  return top
}

export function Hint({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const closing = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const pop = useRef<HTMLSpanElement>(null)
  // the words open above the icon, or below it when above they would be cut off (an icon near the page's top)
  const [below, setBelow] = useState(false)
  useLayoutEffect(() => {
    if (!open) return setBelow(false)
    const el = pop.current
    if (el && !below && el.getBoundingClientRect().top < clipTop(el)) setBelow(true)
  }, [open, below])
  const show = () => {
    clearTimeout(closing.current)
    setOpen(true)
  }
  const hide = () => {
    clearTimeout(closing.current)
    setOpen(false)
  }
  useEffect(() => () => clearTimeout(closing.current), [])
  return (
    <span className="hint" onMouseEnter={show} onMouseLeave={() => (closing.current = setTimeout(hide, GRACE_MS))}>
      <button
        type="button"
        className="hint-icon"
        aria-label={label}
        aria-describedby={open ? id : undefined}
        onFocus={show}
        onBlur={hide}
        onKeyDown={(e) => {
          // the Escape that closes the words is theirs: it does not also leave the screen
          if (e.key === 'Escape' && open) {
            e.stopPropagation()
            hide()
          }
        }}
      >
        <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 11v5.5M12 7.5v.01" />
        </svg>
      </button>
      {open && (
        <span ref={pop} role="tooltip" id={id} className={below ? 'hint-pop small below' : 'hint-pop small'}>
          {children}
        </span>
      )}
    </span>
  )
}
