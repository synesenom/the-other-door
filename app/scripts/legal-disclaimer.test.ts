import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import { legalDisclaimer } from './legal-disclaimer'

type Hooks = { resolveId: (id: string) => string | undefined; load: (this: { addWatchFile: (f: string) => void }, id: string) => string | undefined }

describe('the legal disclaimer plugin', () => {
  const file = join(mkdtempSync(join(tmpdir(), 'disclaimer-')), 'LEGAL.md')
  writeFileSync(file, 'Say "no" \n\nto scraping.\n')
  const plugin = legalDisclaimer(file) as unknown as Hooks

  it('hands the file over as a module, and rebuilds when the file changes', () => {
    const addWatchFile = vi.fn()
    const code = plugin.load.call({ addWatchFile }, plugin.resolveId('virtual:legal-disclaimer')!)!
    expect(code).toBe(`export default ${JSON.stringify('Say "no" \n\nto scraping.\n')}`)
    expect(addWatchFile).toHaveBeenCalledWith(file)
  })

  it('leaves every other module alone', () => {
    expect(plugin.resolveId('react')).toBeUndefined()
    expect(plugin.load.call({ addWatchFile: vi.fn() }, 'react')).toBeUndefined()
  })
})
