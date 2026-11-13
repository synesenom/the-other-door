// The Profile screen's form, pure: the values a config gives each field, what changed, the
// init_profile arguments for the changes, and init_profile's error lines put under their fields.
// The fields and their types come from show_profile's `options.fields` (the Profile model).

export interface FieldSpec {
  key: string
  type: 'string' | 'path' | 'choice' | 'boolean' | 'integer' | 'number' | 'list' | 'exclude'
  required: boolean
  nullable: boolean
  default?: unknown
  min?: number
  max?: number
  choices?: string[]
}

export interface Exclude {
  companies: string[]
  keywords: string[]
}

/**
 * A field's value in the form: text for strings and numbers ('' = none), a list, a flag, or exclude. A flag
 * config.json does not set is null (shown as its default): choosing it, even as the default, is a change.
 */
export type FormValue = string | string[] | boolean | null | Exclude
export type FormValues = Record<string, FormValue>

/** The keys init_profile takes by name; every other key goes in `other`. */
const NAMED = new Set(['name', 'email', 'location', 'languages', 'role_targets', 'search_keywords', 'topic_terms', 'remote', 'min_score'])

function valueOf(spec: FieldSpec, raw: unknown): FormValue {
  switch (spec.type) {
    case 'list':
      return Array.isArray(raw) ? raw.map(String) : []
    case 'boolean':
      return Boolean(raw)
    case 'exclude': {
      const e = (raw ?? {}) as Partial<Exclude>
      return { companies: [...(e.companies ?? [])], keywords: [...(e.keywords ?? [])] }
    }
    default:
      return raw === null || raw === undefined ? '' : String(raw)
  }
}

export function formValues(config: Record<string, unknown> | null, specs: FieldSpec[]): FormValues {
  const values: FormValues = {}
  for (const spec of specs) {
    const set = config !== null && spec.key in config
    values[spec.key] = spec.type === 'boolean' && !set ? null : valueOf(spec, set ? config[spec.key] : spec.default)
  }
  return values
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

export function changedKeys(before: FormValues, after: FormValues): string[] {
  return Object.keys(after).filter((k) => !same(before[k], after[k]))
}

/** What init_profile stores for a field's form value: numbers parsed (as typed when they are not one), '' as null. */
function stored(spec: FieldSpec, value: FormValue): unknown {
  if (spec.type === 'integer' || spec.type === 'number') {
    const text = String(value).trim()
    // empty is "none" only where none is allowed; elsewhere it goes as typed and the server says why
    if (text === '') return spec.nullable ? null : text
    const n = Number(text)
    return Number.isFinite(n) ? n : text
  }
  if (spec.type === 'string' && spec.nullable && value === '') return null
  return value
}

/** The init_profile arguments for what changed. The file paths are shown, never sent. */
export function toInitArgs(before: FormValues, after: FormValues, specs: FieldSpec[]): Record<string, unknown> {
  const args: Record<string, unknown> = {}
  const other: Record<string, unknown> = {}
  for (const key of changedKeys(before, after)) {
    const spec = specs.find((s) => s.key === key)
    if (!spec || spec.type === 'path') continue
    if (spec.type === 'exclude') {
      const was = before[key] as Exclude
      const now = after[key] as Exclude
      if (!same(was.companies, now.companies)) args['exclude_companies'] = now.companies
      if (!same(was.keywords, now.keywords)) args['exclude_keywords'] = now.keywords
      continue
    }
    const value = stored(spec, after[key]!)
    // init_profile's own min_score is a number: text there is refused before the profile is checked,
    // so text goes in `other`, where the profile's check says why under the field
    if (NAMED.has(key) && !(spec.type === 'number' && typeof value === 'string')) args[key] = value
    else other[key] = value
  }
  if (Object.keys(other).length) args['other'] = other
  return args
}

/** init_profile's error lines ("<file>: <key> — <why>") under their fields; the rest above the form. */
export function fieldErrors(text: string, specs: FieldSpec[]): { byKey: Record<string, string[]>; general: string[] } {
  const byKey: Record<string, string[]> = {}
  const general: string[] = []
  for (const line of text.split('\n').map((l) => l.trim()).filter(Boolean)) {
    const m = /^.+?: ([\w.]+) — (.+)$/.exec(line)
    const key = m ? m[1]!.split('.')[0]! : null
    if (m && key && specs.some((s) => s.key === key)) (byKey[key] ??= []).push(m[2]!)
    else general.push(line)
  }
  return { byKey, general }
}
