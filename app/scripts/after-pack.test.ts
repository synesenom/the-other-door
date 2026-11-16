import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const { machOFiles } = createRequire(import.meta.url)('./after-pack.cjs') as { machOFiles: (dir: string) => string[] }

describe('after-pack machOFiles', () => {
  it('lists the Mach-O files under a folder, the deepest first, by their first bytes', () => {
    const dir = mkdtempSync(join(tmpdir(), 'afterpack-'))
    mkdirSync(join(dir, 'chromium', 'lib'), { recursive: true })
    writeFileSync(join(dir, 'chromium', 'shell'), Buffer.from([0xcf, 0xfa, 0xed, 0xfe, 7, 0, 0, 1]))
    writeFileSync(join(dir, 'chromium', 'lib', 'libx.dylib'), Buffer.from([0xce, 0xfa, 0xed, 0xfe, 7, 0, 0, 0]))
    writeFileSync(join(dir, 'chromium', 'icudtl.dat'), 'data')
    expect(machOFiles(dir)).toEqual([join(dir, 'chromium', 'lib', 'libx.dylib'), join(dir, 'chromium', 'shell')])
  })
})
