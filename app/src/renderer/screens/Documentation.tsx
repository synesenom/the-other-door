import { useState } from 'react'
import { Dialog } from './Dialog'
import { Markdown } from './Markdown'
// The repo's LEGAL_DISCLAIMER.md, built into the app (scripts/legal-disclaimer.ts).
import disclaimer from 'virtual:legal-disclaimer'

export interface Doc {
  title: string
  text: string
}

export const LEGAL_DISCLAIMER: Doc = { title: 'Legal disclaimer', text: disclaimer }

/** The app's manual, read in the browser on GitHub (it follows main, which can be ahead of an installed release). */
export const USER_GUIDE = 'https://github.com/synesenom/the-other-door/blob/main/docs/manual-app.md'

/** Every document the app carries: a new one is a line here. */
const DOCS: Doc[] = [LEGAL_DISCLAIMER]

/** A document in a dialog: what the user was doing stays behind it, as it was. */
export function DocDialog({ doc, onClose }: { doc: Doc; onClose: () => void }) {
  // The dialog's title stands for the file's first heading (Windows line endings or not).
  const body = doc.text.replace(/^# [^\r\n]*(?:\r?\n)+/, '')
  return (
    <Dialog title={doc.title} onClose={onClose}>
      <Markdown text={body} className="doc-text" />
      <div className="actions">
        <button type="button" className="secondary" onClick={onClose}>
          Close
        </button>
      </div>
    </Dialog>
  )
}

/** The user guide (in the browser) and the documents, one text button each on its own line, in Settings' Help. */
export function Documentation() {
  const [open, setOpen] = useState<Doc | null>(null)
  return (
    <>
      <ul className="doc-list">
        <li>
          <button type="button" className="secondary go" onClick={() => void window.door.invoke('open-external', USER_GUIDE)}>
            User guide
          </button>
        </li>
        {DOCS.map((doc) => (
          <li key={doc.title}>
            <button type="button" className="secondary" onClick={() => setOpen(doc)}>
              {`${doc.title}…`}
            </button>
          </li>
        ))}
      </ul>
      {open && <DocDialog doc={open} onClose={() => setOpen(null)} />}
    </>
  )
}
