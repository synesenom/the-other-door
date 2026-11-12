import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { generateTheme } from './theme.ts'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tokens = JSON.parse(readFileSync(join(app, '..', 'docs', 'design', 'tokens.json'), 'utf8'))
writeFileSync(join(app, 'src', 'renderer', 'theme.css'), generateTheme(tokens))
console.log('wrote src/renderer/theme.css')
