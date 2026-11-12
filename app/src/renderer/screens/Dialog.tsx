import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'

interface Props {
  title: string
  onClose: () => void
  children: ReactNode
  /** A CSS selector inside the dialog for the control that takes focus first; else the first control. */
  initialFocus?: string
}

const FOCUSABLE = 'button:not([disabled]), textarea, [href], input, select, [tabindex]:not([tabindex="-1"])'

/** The shared modal: a scrim, a titled panel, focus kept inside, Escape to leave. */
export function Dialog({ title, onClose, children, initialFocus }: Props) {
  const dialog = useRef<HTMLDivElement>(null)
  const titleId = useId()

  useEffect(() => {
    const root = dialog.current
    if (!root) return
    const target = (initialFocus && root.querySelector<HTMLElement>(initialFocus)) || root.querySelector<HTMLElement>(FOCUSABLE)
    target?.focus()
    // only on opening: a later render must not pull focus back
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.stopPropagation()
      onClose()
    } else if (e.key === 'Tab' && dialog.current) {
      const items = Array.from(dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE))
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
  }

  return (
    <div className="scrim">
      <div ref={dialog} className="dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={onKeyDown}>
        <h2 id={titleId} className="display-s">
          {title}
        </h2>
        {children}
      </div>
    </div>
  )
}
