import { Fragment } from 'react'
import type { ReactNode } from 'react'

const NAME = 'The other door'

/** The app's name in a sentence: in the display face, so it reads as a name and not as a phrase. */
export function AppName() {
  return <span className="app-name">{NAME}</span>
}

/** A message that may name the app, its own words or the server's, with the name set as `AppName`. Anything else stays as it is. */
export function named(message: ReactNode): ReactNode {
  if (typeof message !== 'string' || !message.includes(NAME)) return message
  return message.split(NAME).map((part, i) => (
    <Fragment key={i}>
      {i > 0 && <AppName />}
      {part}
    </Fragment>
  ))
}
