// `TODO` is how a CV draft marks what it could not find: one gap per word, wherever it sits on a line.
export const TODO_WORD = /\bTODO\b/g

/** Where each gap starts in the CV's text, in order. */
export function todoOffsets(text: string): number[] {
  return [...text.matchAll(TODO_WORD)].map((m) => m.index)
}
