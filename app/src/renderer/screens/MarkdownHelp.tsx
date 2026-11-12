import { openExternal } from '../api'

/** The Markdown Guide's one-page cheatsheet, opened in the browser. */
export const MARKDOWN_CHEATSHEET = 'https://www.markdownguide.org/cheat-sheet/'

/**
 * The word "Markdown" after a Markdown editor's name ("Your CV (Markdown)"), as a link to how it is written. It
 * sits beside the <label>, not in it, so a click opens the cheatsheet and not the editor.
 */
export function MarkdownLink() {
  return (
    <button type="button" className="link-inline" title="Markdown cheatsheet" onClick={() => void openExternal(MARKDOWN_CHEATSHEET)}>
      Markdown
    </button>
  )
}
