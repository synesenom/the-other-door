import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(join(__dirname, 'styles.css'), 'utf8')

describe('styles.css', () => {
  // Hex colours are refused for every renderer file by scripts/theme.test.ts.
  it('takes every colour from a token: no rgb() and no color-mix', () => {
    expect(css).not.toMatch(/rgba?\(|color-mix/)
  })

  describe('the narrow layout', () => {
    const tokens = JSON.parse(readFileSync(join(__dirname, '..', '..', '..', 'docs', 'design', 'tokens.json'), 'utf8'))
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
      for (const v of ['--phone-row-min-height', '--phone-tab-bar-label', '--phone-tab-bar-dash-width', '--phone-tab-bar-dash-height', '--phone-tab-bar-bottom-inset', '--phone-gutter', '--phone-text-display-l-size', '--phone-text-score-l-size']) {
        expect(block, v).toContain(`var(${v})`)
      }
    })
  })
})
