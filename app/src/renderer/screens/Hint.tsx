import { useEffect, useId, useRef, useState } from 'react'
import type { ReactNode } from 'react'

/**
 * Words that would crowd the page, behind an info icon: open while the pointer is on the icon or the words,
 * or while the icon has the keyboard's focus; Escape closes them. A moment's grace after the pointer leaves,
 * so a diagonal way from the icon to the words does not close them.
 */
const GRACE_MS = 200

export function Hint({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const closing = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
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
        <span role="tooltip" id={id} className="hint-pop small">
          {children}
        </span>
      )}
    </span>
  )
}
