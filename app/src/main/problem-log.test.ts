import { existsSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { createProblemLog, MAX_BYTES } from './problem-log'

const NOW = new Date('2026-10-26T09:00:00.123Z')
const home = () => mkdtempSync(join(tmpdir(), 'problem-log-'))

describe('the problem log, from the main process', () => {
  it('appends one line to <home>/logs/door.log, the server\'s own file and format', () => {
    const h = home()
    const log = createProblemLog(h, { now: () => NOW })
    log.write('refused import_data', 'import_data cannot take a file path from the window')
    log.write('server stopped', 'Traceback (most recent call last):\nRuntimeError: boom')
    expect(readFileSync(join(h, 'logs', 'door.log'), 'utf8')).toBe(
      '2026-10-26T09:00:00Z ERROR app refused import_data: import_data cannot take a file path from the window\n' +
        '2026-10-26T09:00:00Z ERROR app server stopped: Traceback (most recent call last): RuntimeError: boom\n',
    )
  })

  it('keeps a line bounded', () => {
    const h = home()
    createProblemLog(h, { now: () => NOW }).write('server stopped', 'x'.repeat(10_000))
    expect(readFileSync(join(h, 'logs', 'door.log'), 'utf8').length).toBeLessThan(2100)
  })

  it('rotates a full log as the server does: door.log.1, door.log.2, no more', () => {
    const h = home()
    const log = createProblemLog(h, { now: () => NOW })
    log.write('first', 'a')
    const full = join(h, 'logs', 'door.log')
    for (const n of [1, 2, 3]) {
      writeFileSync(full, `${n}`.repeat(MAX_BYTES))
      log.write('after', `rotation ${n}`)
    }
    expect(readdirSync(join(h, 'logs')).sort()).toEqual(['door.log', 'door.log.1', 'door.log.2'])
    expect(readFileSync(full, 'utf8')).toContain('rotation 3')
    expect(readFileSync(join(h, 'logs', 'door.log.1'), 'utf8').startsWith('3')).toBe(true)
    expect(readFileSync(join(h, 'logs', 'door.log.2'), 'utf8').startsWith('2')).toBe(true)
  })

  it('never throws, and writes nothing when the data folder is gone', () => {
    const missing = join(home(), 'gone')
    expect(() => createProblemLog(missing).write('server stopped', 'x')).not.toThrow()
    expect(existsSync(missing)).toBe(false)
  })
})
