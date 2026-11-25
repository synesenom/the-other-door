import type { Document, SetStatusResult } from '../api'
import { Materials } from './Materials'
import { Posting } from './Posting'

export type PaneView = 'posting' | 'materials'

interface Props {
  jobId: string
  view: PaneView
  onView: (view: PaneView) => void
  /** A status was saved (from the posting or from "I've applied"), on the job titled `title`. */
  onChanged: (result: SetStatusResult, title: string) => void
  /** The document Ready to send opens on (a clicked notification); else the one its first warning names, the CV when none. */
  initialDoc?: Document
  /** Ready to send's back link: its words and where it goes; "Posting" to the posting when left out. */
  back?: { label: string; onBack: () => void }
}

/** What the reading pane (wide) or the pushed screen (narrow) shows for one job: its posting, or its prepared application. */
export function ReadingPane({ jobId, view, onView, onChanged, initialDoc, back }: Props) {
  if (view === 'materials') return <Materials key={jobId} jobId={jobId} onBack={back?.onBack ?? (() => onView('posting'))} backLabel={back?.label} onPosting={back ? () => onView('posting') : undefined} onApplied={onChanged} initialDoc={initialDoc} />
  return <Posting key={jobId} jobId={jobId} onChanged={onChanged} onOpenMaterials={() => onView('materials')} />
}
