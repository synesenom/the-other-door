import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(join(__dirname, 'styles.css'), 'utf8')

/** The rules (selector blocks) whose body mentions `needle`. */
function rulesUsing(needle: string): string[] {
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter((m) => m[2].includes(needle)).map((m) => m[1].trim())
}

describe('styles.css', () => {
  it('draws thin scrollbars in the theme colours, with no track, everywhere', () => {
    const all = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].find((m) => m[1].trim() === '*')?.[2] ?? ''
    expect(all).toContain('scrollbar-width: thin')
    expect(all).toContain('scrollbar-color: var(--color-border) transparent')
  })

  it('lets the posting fill its pane, with the score reason kept to a reading measure', () => {
    const body = (selector: string) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].find((m) => m[1].trim() === selector)?.[2] ?? ''
    expect(body('.posting')).not.toContain('max-width')
    expect(body('.reason')).toContain('max-width: 60ch')
  })

  it('from 900 px (side by side) each document scrolls its own pages, under a view that fits the window', () => {
    const wide = css.match(/@media \(min-width: 900px\) \{([\s\S]*?)\n\}/)?.[1] ?? ''
    const rule = (selector: string) => wide.match(new RegExp(`(^|\\n)\\s*${selector.replace(/[.*]/g, '\\$&')} \\{([^}]*)\\}`))?.[2] ?? ''
    expect(rule('.pages-stack')).toContain('overflow-y: auto')
    expect(rule('.pages-stack')).toContain('min-height: 0')
    expect(rule('.materials-aside')).toContain('overflow-y: auto')
    expect(rule('.materials')).toContain('height: 100%')
    // Save ends on the line of the sidebar's Find new jobs: 20 px from the bottom.
    expect(wide).toMatch(/\.reading-pane:has\(> \.materials\) \{[^}]*padding-bottom: var\(--space-5\)/)
    // One readable document: the page fills its column instead of a 280 px thumbnail.
    expect(rule('.paper-figure')).toContain('width: 100%')
  })

  it('lets the document take all the width beside the Revise column', () => {
    const body = (selector: string) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].find((m) => m[1].trim() === selector)?.[2] ?? ''
    expect(body('.materials')).not.toContain('max-width')
    expect(body('.paper-figure')).not.toContain('max-width')
    const all = (selector: string) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter((m) => m[1].trim() === selector).map((m) => m[2]).join(' ')
    expect(all('.materials-aside')).toContain('flex: 0 1 360px')
    expect(css).toMatch(/\n\.pages \{[^}]*flex: 1 1 600px/)
    expect(all('.materials-body')).not.toContain('flex-wrap: wrap')
    expect(all('.materials')).not.toContain('max-width')
    expect(all('.paper-figure')).not.toContain('max-width')
  })

  describe('the materials view', () => {
    const body = (selector: string) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].find((m) => m[1].trim() === selector)?.[2] ?? ''

    it('has the paper sheet and the document switch', () => {
      expect(body('.paper')).toContain('var(--color-page)')
      expect(body('.paper')).toContain('border-radius: var(--radius-s)')
      expect(body('.paper')).not.toContain('shadow')
      expect(body('.doc-switch')).not.toBe('')
    })

    it('takes every colour from a token', () => {
      for (const selector of ['.paper', '.paper-figure', '.materials-aside', '.revise textarea']) {
        expect(body(selector), selector).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgba?\(/)
      }
    })
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
