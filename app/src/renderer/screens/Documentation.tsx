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

/** Every document the app carries: a new one is a line here. */
const DOCS: Doc[] = [LEGAL_DISCLAIMER]

/** A document in a dialog: what the user was doing stays behind it, as it was. */
export function DocDialog({ doc, onClose }: { doc: Doc; onClose: () => void }) {
  // The dialog's title stands for the file's first heading.
  const body = doc.text.replace(/^# .*\n+/, '')
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

/** Settings' Documentation, between Your data and Report a problem: the documents, one quiet link each. */
export function Documentation() {
  const [open, setOpen] = useState<Doc | null>(null)
  return (
    <section className="part" aria-labelledby="settings-docs">
      <h2 className="display-s" id="settings-docs">
        Documentation
      </h2>
      <ul className="doc-list">
        {DOCS.map((doc) => (
          <li key={doc.title}>
            <button type="button" className="link-inline small" onClick={() => setOpen(doc)}>
              {doc.title}
            </button>
          </li>
        ))}
      </ul>
      {open && <DocDialog doc={open} onClose={() => setOpen(null)} />}
    </section>
  )
}
