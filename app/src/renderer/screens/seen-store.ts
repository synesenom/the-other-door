// The matches opened in this window: no longer new, whatever the list says, and the ones the server has
// not taken yet (a run holds the ledger, so `mark_seen` is refused until it ends), sent again on each
// reload. They outlive Matches, which the window mounts afresh when a run ends.
export const seenHere = new Set<string>()
export const unsentSeen = new Set<string>()
