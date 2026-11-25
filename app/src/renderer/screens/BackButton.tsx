// A pushed screen's way back: the drawn arrow, then the label ("Matches"). The arrow is drawn (`.back-arrow`), not
// taken from a font, so it is the same size and on the same line on every system; the "←" stays in the text, so the
// button is still named "← Matches".
export function BackButton({ label, onClick, title }: { label: string; onClick: () => void; title?: string }) {
  return (
    <button type="button" className="back" onClick={onClick} title={title}>
      <span className="back-arrow">←</span> {label}
    </button>
  )
}
