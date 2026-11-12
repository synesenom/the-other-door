/** The done mark: two straight strokes meeting at a right angle, sized by the text around it. */
export function CheckMark() {
  return (
    <svg className="check-mark" viewBox="0 0 16 16" aria-hidden="true">
      <polyline points="2.75,8.25 6.25,11.75 13.25,4.75" />
    </svg>
  )
}

/** The failed mark: the check's strokes, crossed and centred, so the two sit alike beside a label. */
export function CrossMark() {
  return (
    <svg className="check-mark" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M4,4 L12,12 M12,4 L4,12" />
    </svg>
  )
}

/** The warning mark: a triangle in the warning colour with a ! on it, before a line that needs the user. */
export function WarningMark() {
  return (
    <svg className="warning-mark" viewBox="0 0 16 16" aria-hidden="true">
      <path className="warning-mark-shape" d="M8 1.5 L15 14 H1 Z" />
      <path className="warning-mark-bang" d="M8 6 V9.75 M8 11.5 V12" />
    </svg>
  )
}
