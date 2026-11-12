import { useState } from 'react'
import { DocDialog, LEGAL_DISCLAIMER } from './Documentation'

/** "LinkedIn", "LinkedIn and HelloWork", "A, B and C". */
export const andList = (names: string[]) => (names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`)

/** The "legal disclaimer" link that opens the document in a dialog, shared by every line that names the discovery sources. */
export function LegalLink() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" className="link-inline" onClick={() => setOpen(true)}>
        legal disclaimer
      </button>
      {open && <DocDialog doc={LEGAL_DISCLAIMER} onClose={() => setOpen(false)} />}
    </>
  )
}
