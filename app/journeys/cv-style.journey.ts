// Profile → Style: the sample of the CV, a colour and a font pair picked and saved at once.
import { expect, test } from './fixtures'
import { argsOf, config, openDetails } from './helpers/profile'

test.describe('Style', () => {
  test('shows a sample of the CV, and a pick is saved at once and printed again', { tag: '@core' }, async ({ page, world }) => {
    await openDetails(page)
    await page.getByRole('navigation', { name: 'Sections' }).getByRole('link', { name: 'Style', exact: true }).click()
    const part = page.getByRole('region', { name: 'Style', exact: true })
    await expect(part.getByRole('img', { name: /sample of your CV/ })).toBeVisible({ timeout: 60_000 })
    await expect(part.getByRole('radio', { name: 'Blue' })).toBeChecked()
    await expect(part.getByRole('radio', { name: 'The other door' })).toBeChecked()
    expect(config(world)['cv_accent']).toBeUndefined()

    const before = argsOf(world, 'cv_style_sample').length
    await part.getByRole('radio', { name: 'Teal' }).check()
    await expect.poll(() => config(world)['cv_accent']).toBe('teal')
    await expect.poll(() => argsOf(world, 'cv_style_sample').length).toBeGreaterThan(before)
    expect(argsOf(world, 'cv_style_sample').at(-1)).toEqual({ cv_accent: 'teal', cv_fonts: 'door' })
    expect(argsOf(world, 'init_profile').at(-1)).toEqual({ other: { cv_accent: 'teal' } })
    await expect(part.getByRole('img', { name: /sample of your CV/ })).toBeVisible()

    await part.getByRole('radio', { name: 'Editorial' }).check()
    await expect.poll(() => config(world)['cv_fonts']).toBe('editorial')
    expect(config(world)['cv_accent']).toBe('teal')
  })
})
