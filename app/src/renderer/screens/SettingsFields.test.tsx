// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { mockDoor } from '../testing'
import { SettingsFields } from './SettingsFields'
import type { FieldSpec } from './profile-form/form'

afterEach(cleanup)

const FIELDS: FieldSpec[] = [
  { key: 'name', type: 'string', required: true, nullable: false },
  { key: 'location', type: 'string', required: true, nullable: false },
  { key: 'linkedin_discovery', type: 'boolean', required: false, nullable: false, default: false },
  { key: 'profession_discovery', type: 'boolean', required: false, nullable: false, default: false },
  { key: 'follow_ai_fallback', type: 'boolean', required: false, nullable: false, default: true },
]
const linkedin = { key: 'linkedin_discovery', label: 'LinkedIn', disclaimer: 'LinkedIn: its terms ask for no scrapers. Your decision, at your own risk.' }
const profession = { key: 'profession_discovery', label: 'profession.hu' }
const OPTIONS = {
  cities: [
    { name: 'Copenhagen', country: 'Denmark', boards: ['jobindex'], discovery: [linkedin] },
    { name: 'Budapest', country: 'Hungary', boards: [], discovery: [linkedin, profession] },
  ],
  languages: ['English'],
  worldwide_boards: [],
  worldwide_discovery: [linkedin],
  fields: FIELDS,
}
const show = (config: Record<string, unknown> = {}) => ({
  path: '/home/ada/profile',
  config: { name: 'Ada', location: 'Copenhagen', ...config },
  errors: [],
  options: OPTIONS,
})

function open(section: string, config: Record<string, unknown> = {}, handlers: Record<string, unknown> = {}) {
  const h = mockDoor({ show_profile: show(config), init_profile: { config_path: '/x' }, ...handlers })
  render(
    <section aria-label="part">
      <SettingsFields section={section} />
    </section>,
  )
  return h
}
const switches = async () => (await screen.findAllByRole('checkbox')).map((c) => c.closest('label')?.textContent ?? '').join(' | ')

describe('SettingsFields, Risky sources', () => {
  it('only the sources serving your city, even one switched on that does not', async () => {
    open('risky', { profession_discovery: true })
    const shown = await switches()
    expect(shown).toMatch(/LinkedIn/)
    expect(shown).not.toMatch(/profession/)
  })

  it('a source that is on shows its disclaimer; once it is off, it does not', async () => {
    open('risky', { linkedin_discovery: true })
    expect(await screen.findByText(/LinkedIn: its terms ask for no scrapers/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('checkbox', { name: /LinkedIn/ }))
    expect(screen.queryByText(/LinkedIn: its terms ask for no scrapers/)).toBeNull()
  })

  it('a city in no known country: the worldwide ones', async () => {
    open('risky', { location: 'Reykjavik' })
    expect(await switches()).not.toMatch(/profession/)
  })

  it('a tick is saved at once, with nothing else', async () => {
    const { call } = open('risky')
    await userEvent.click(await screen.findByRole('checkbox', { name: 'LinkedIn' }))
    await waitFor(() => expect(call).toHaveBeenCalledWith('init_profile', { other: { linkedin_discovery: true } }))
    expect(screen.getByRole('checkbox', { name: 'LinkedIn' })).toBeChecked()
  })

  it('a refusal is said under the switch', async () => {
    open('risky', {}, {
      init_profile: () => {
        throw { message: 'profile/config.json: linkedin_discovery — Input should be a valid boolean' }
      },
    })
    await userEvent.click(await screen.findByRole('checkbox', { name: 'LinkedIn' }))
    const field = screen.getByRole('checkbox', { name: 'LinkedIn' }).closest('.field') as HTMLElement
    expect(await within(field).findByText('Input should be a valid boolean')).toBeInTheDocument()
  })
})
