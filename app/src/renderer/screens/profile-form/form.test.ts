import { describe, expect, it } from 'vitest'
import { changedKeys, fieldErrors, formValues, toInitArgs, type FieldSpec } from './form'

const specs: FieldSpec[] = [
  { key: 'name', type: 'string', required: true, nullable: false },
  { key: 'cv_template', type: 'path', required: true, nullable: false },
  { key: 'role_targets', type: 'list', required: true, nullable: false },
  { key: 'remote', type: 'choice', required: true, nullable: false, choices: ['yes', 'no', 'hybrid'] },
  { key: 'exclude', type: 'exclude', required: false, nullable: false, default: { companies: [], keywords: [] } },
  { key: 'min_score', type: 'number', required: false, nullable: false, default: 0.65 },
  { key: 'max_age_days', type: 'integer', required: false, nullable: true, default: 30, min: 1 },
  { key: 'scrape_workers', type: 'integer', required: false, nullable: true, default: null, min: 1 },
  { key: 'translate_titles', type: 'boolean', required: false, nullable: false, default: true },
  { key: 'claude_config_dir', type: 'string', required: false, nullable: true, default: null },
  { key: 'sectors', type: 'string', required: false, nullable: false, default: '' },
]

const config = { name: 'Ada', cv_template: '/p/cv.template.tex', role_targets: ['Analyst'], remote: 'hybrid', min_score: 0.7, exclude: { companies: ['Acme'] } }

describe('formValues', () => {
  it('takes what the config sets, else the default; numbers as text, null as empty, a switch never set as null', () => {
    expect(formValues(config, specs)).toEqual({
      name: 'Ada',
      cv_template: '/p/cv.template.tex',
      role_targets: ['Analyst'],
      remote: 'hybrid',
      exclude: { companies: ['Acme'], keywords: [] },
      min_score: '0.7',
      max_age_days: '30',
      scrape_workers: '',
      translate_titles: null,
      claude_config_dir: '',
      sectors: '',
    })
  })

  it('a missing required value starts empty', () => {
    const v = formValues({}, specs)
    expect(v['name']).toBe('')
    expect(v['role_targets']).toEqual([])
  })
})

describe('changedKeys and toInitArgs', () => {
  const before = formValues(config, specs)

  it('nothing changed, nothing sent', () => {
    expect(changedKeys(before, { ...before })).toEqual([])
    expect(toInitArgs(before, { ...before }, specs)).toEqual({})
  })

  it('the named fields go by name, the rest in other, typed', () => {
    const after = { ...before, name: 'Ada L.', min_score: '0.75', max_age_days: '14', translate_titles: false, scrape_workers: '4' }
    expect(changedKeys(before, after).sort()).toEqual(['max_age_days', 'min_score', 'name', 'scrape_workers', 'translate_titles'])
    expect(toInitArgs(before, after, specs)).toEqual({ name: 'Ada L.', min_score: 0.75, other: { max_age_days: 14, translate_titles: false, scrape_workers: 4 } })
  })

  it('an emptied nullable field is null; an emptied optional text field is null too', () => {
    const after = { ...before, max_age_days: '', claude_config_dir: '' }
    const later = { ...after, claude_config_dir: '~/.claude-work' }
    expect(toInitArgs(before, after, specs)).toEqual({ other: { max_age_days: null } })
    expect(toInitArgs(before, later, specs)).toEqual({ other: { max_age_days: null, claude_config_dir: '~/.claude-work' } })
    expect(toInitArgs(formValues({ ...config, claude_config_dir: '/x' }, specs), { ...before, claude_config_dir: '' }, specs)).toEqual({ other: { claude_config_dir: null } })
  })

  it('an emptied number that may not be empty goes as typed in other, for the server to explain under its field', () => {
    // init_profile's own min_score argument is a number: text there is refused before the profile is checked
    expect(toInitArgs(before, { ...before, min_score: '' }, specs)).toEqual({ other: { min_score: '' } })
    expect(toInitArgs(before, { ...before, min_score: 'abc' }, specs)).toEqual({ other: { min_score: 'abc' } })
  })

  it('a switch never set is a change once chosen, even as its default', () => {
    const unset = formValues({ ...config }, specs)
    expect(changedKeys(unset, { ...unset, translate_titles: true })).toEqual(['translate_titles'])
    expect(toInitArgs(unset, { ...unset, translate_titles: false }, specs)).toEqual({ other: { translate_titles: false } })
  })

  it('a number that is not one goes as typed, for the server to explain', () => {
    expect(toInitArgs(before, { ...before, max_age_days: 'soon' }, specs)).toEqual({ other: { max_age_days: 'soon' } })
  })

  it('exclude goes as exclude_companies and exclude_keywords, only the part that changed', () => {
    const after = { ...before, exclude: { companies: ['Acme'], keywords: ['junior'] } }
    expect(toInitArgs(before, after, specs)).toEqual({ exclude_keywords: ['junior'] })
  })

  it('lists and choices go by name when init_profile names them', () => {
    const after = { ...before, role_targets: ['Analyst', 'Data Scientist'], remote: 'yes' }
    expect(toInitArgs(before, after, specs)).toEqual({ role_targets: ['Analyst', 'Data Scientist'], remote: 'yes' })
  })

  it('the file paths are never sent', () => {
    expect(toInitArgs(before, { ...before, cv_template: '/etc/passwd' }, specs)).toEqual({})
  })
})

describe('fieldErrors', () => {
  it('puts each line under its key, exclude.* under exclude, and the rest above the form', () => {
    const text = [
      'profile/config.json: remote — Input should be \'yes\', \'no\' or \'hybrid\'',
      '/Users/ada/data/profile/config.json: max_age_days — Input should be greater than or equal to 1',
      'profile/config.json: exclude.keywords — Input should be a valid list',
      'profile/config.json: bogus — Extra inputs are not permitted',
      'something went wrong',
    ].join('\n')
    expect(fieldErrors(text, specs)).toEqual({
      byKey: {
        remote: ["Input should be 'yes', 'no' or 'hybrid'"],
        max_age_days: ['Input should be greater than or equal to 1'],
        exclude: ['Input should be a valid list'],
      },
      general: ['profile/config.json: bogus — Extra inputs are not permitted', 'something went wrong'],
    })
  })
})

describe('sectors, a free-text string that is never null', () => {
  const before = formValues({ ...config, sectors: 'robotics' }, specs)

  it('sends a changed text in other', () => {
    expect(toInitArgs(before, { ...before, sectors: 'medical; not banking' }, specs)).toEqual({ other: { sectors: 'medical; not banking' } })
  })

  it('sends "" when cleared, not null', () => {
    expect(toInitArgs(before, { ...before, sectors: '' }, specs)).toEqual({ other: { sectors: '' } })
  })

  it('sends nothing when unchanged', () => {
    expect(toInitArgs(before, { ...before }, specs)).toEqual({})
  })
})
