import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(join(__dirname, 'styles.css'), 'utf8')
const tokens = JSON.parse(readFileSync(join(__dirname, '..', '..', '..', 'docs', 'design', 'tokens.json'), 'utf8'))

describe('styles.css', () => {
  // Hex colours are refused for every renderer file by scripts/theme.test.ts.
  it('takes every colour from a token: no rgb() and no color-mix', () => {
    expect(css).not.toMatch(/rgba?\(|color-mix/)
  })

  // A screen's width is size.column-width or size.wide-width (PR 536): screens that typed their own drifted apart.
  describe('screen widths', () => {
    const column = tokens.size['column-width'] as number
    const typedWidths = (sheet: string): string[] =>
      sheet
        .replace(/@(media|container)[^{]*\{/g, '{')
        .split('\n')
        .flatMap((line, i) =>
          [...line.matchAll(/(\d+(?:\.\d+)?)(px|rem)\b/g)]
            .filter((m) => Number(m[1]) * (m[2] === 'rem' ? 16 : 1) >= column)
            .map((m) => `${i + 1}: ${m[0]}`),
        )

    it('types no width as wide as a column: it reads var(--size-column-width) or var(--size-wide-width)', () => {
      const web = readFileSync(join(__dirname, '..', 'web', 'web.css'), 'utf8')
      expect({ styles: typedWidths(css), web: typedWidths(web) }).toEqual({ styles: [], web: [] })
    })

    it('finds a typed column width in any shape, not a small width or a query', () => {
      expect(typedWidths('.a { max-width: min(620px, 100%); flex: 0 1 38.75rem; }')).toEqual(['1: 620px', '1: 38.75rem'])
      expect(typedWidths('.b { width: min(480px, 90vw); flex: 1 1 600px; }\n@media (min-width: 900px) { .c { gap: 4px } }')).toEqual([])
    })
  })

  describe('the narrow layout', () => {
    const queries = [...css.matchAll(/@media \(max-width: (\d+)px\)\s*\{/g)]

    it('has one width media query, one pixel under the sidebar breakpoint', () => {
      expect(queries).toHaveLength(1)
      expect(Number(queries[0][1])).toBe(tokens.size['sidebar-breakpoint'] - 1)
    })

    it('takes its sizes from the --phone-* variables', () => {
      const start = queries[0].index as number
      let depth = 0
      let end = start
      for (let i = css.indexOf('{', start); i < css.length; i++) {
        if (css[i] === '{') depth++
        if (css[i] === '}' && --depth === 0) {
          end = i
          break
        }
      }
      const block = css.slice(start, end)
      for (const v of ['--phone-row-min-height', '--phone-tab-bar-label', '--phone-tab-bar-bottom-inset', '--phone-gutter']) {
        expect(block, v).toContain(`var(${v})`)
      }
    })
  })
})
