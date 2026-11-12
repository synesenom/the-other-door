/** A switch: one setting on or off, its name beside it (the CV's Preview over its Markdown). A pill group
 *  chooses between several views; a switch turns one on. */
export function Switch({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <button type="button" role="switch" aria-checked={checked} className="switch" onClick={() => onChange(!checked)}>
      <span className="switch-track" aria-hidden="true">
        <span className="switch-thumb" />
      </span>
      <span>{label}</span>
    </button>
  )
}
