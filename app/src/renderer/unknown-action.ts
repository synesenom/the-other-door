/** What the test stand-in (`testing.ts`) and the preview mock (`preview/mock-door.ts`) both answer for an action they have no answer to. */
export const unknownAction = (action: string): string => `unknown action ${action}`
