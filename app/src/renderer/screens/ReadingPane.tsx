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
  /** The document Ready to send opens on (a clicked notification); the letter when left out. */
  initialDoc?: Document
}

/** What the reading pane (wide) or the pushed screen (narrow) shows for one job: its posting, or its prepared application. */
export function ReadingPane({ jobId, view, onView, onChanged, initialDoc }: Props) {
  if (view === 'materials') return <Materials key={jobId} jobId={jobId} onBack={() => onView('posting')} onApplied={onChanged} initialDoc={initialDoc} />
  return <Posting key={jobId} jobId={jobId} onChanged={onChanged} onOpenMaterials={() => onView('materials')} />
}
