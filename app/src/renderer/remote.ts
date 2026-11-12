// The phone app (issue 303) runs these screens over `door serve`: what only the door machine can do
// (sign in to Claude, install, connect Drive, file dialogs, the data folder, first-time setup) says so there.
import { createContext, useContext } from 'react'

export const RemoteContext = createContext(false)

/** True in the phone app. */
export function useRemote(): boolean {
  return useContext(RemoteContext)
}

export const ON_THE_MACHINE = 'Do this on the computer running The other door.'
