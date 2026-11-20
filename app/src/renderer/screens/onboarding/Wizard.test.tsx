// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../../testing'
import { cvState, doctorReport, existingProfile, freshProfile } from './testing'
import { Wizard } from './Wizard'

afterEach(cleanup)

const saved = { ...existingProfile, cv: cvState({ exists: true, is_example: false, text: '# Ada' }) }
const happy = {
  doctor: doctorReport('ok'), draft_cv: { markdown: '# Ada\n', provenance: [], todos: [], sources: [] },
  infer_basics: { name: 'Ada', email: 'ada@x.dk', location: 'Aarhus', languages: ['English'], remote: 'hybrid', missing: [] },
  suggest_titles: { titles: [{ title: 'Lead', reason: 'you led', recommended: true }] }, keywords: { keywords: ['lead'], topic_terms: ['data'] },
  init_profile: {}, save_cv: {}, show_profile: saved,
}

function setup(extra: Record<string, unknown> = {}, props: Partial<Parameters<typeof Wizard>[0]> = {}) {
  const h = mockDoor({ ...happy, ...extra })
  h.pickCvFiles.mockResolvedValue({ files: [{ token: 't', name: 'cv.pdf', size: 1 }], refused: [] })
  const onFinish = vi.fn()
  const view = render(<Wizard profile={freshProfile} environment="production" onFinish={onFinish} {...props} />)
  return { ...h, onFinish, unmount: view.unmount }
}

async function toReview() {
  await userEvent.click(await screen.findByRole('button', { name: 'Drop relevant documents here (CV or LinkedIn PDF)' }))
  await screen.findByText('cv.pdf')
  await waitFor(() => expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled())
  await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
  await screen.findByRole('heading', { name: 'Check your answers' })
}

describe('Wizard', () => {
  it('offers Google Drive on a first set-up, and a pull ends the wizard without a run', async () => {
    const h = setup({ connect_drive: { account: 'ada@example.com' }, sync_data: { action: 'pull' } })
    await userEvent.click(await screen.findByRole('button', { name: 'Bring my profile from Google Drive' }))
    await waitFor(() => expect(h.onFinish).toHaveBeenCalledWith(false))
    expect(h.call.mock.calls.map((c) => c[0])).not.toContain('init_profile')
  })

  it('has no Drive choice in staging or the sandbox, nor when a profile exists (set up again)', async () => {
    for (const environment of ['staging', 'sandbox'] as const) {
      setup({}, { environment })
      await screen.findByRole('heading', { name: 'Tell me about yourself' })
      expect(screen.queryByRole('button', { name: 'Bring my profile from Google Drive' })).toBeNull()
      cleanup()
    }
    setup({}, { profile: saved })
    await screen.findByRole('heading', { name: 'Tell me about yourself' })
    expect(screen.queryByRole('button', { name: 'Bring my profile from Google Drive' })).toBeNull()
  })

  it('is three screens, with no other step on a good CV', async () => {
    setup()
    expect(await screen.findAllByRole('listitem', { name: /Step \d of 3/ })).toHaveLength(3)
    expect(screen.getByRole('heading', { name: 'Tell me about yourself' })).toBeInTheDocument()
    await toReview()
    expect(screen.getByLabelText('Name')).toHaveValue('Ada')
  })

  it('the review lists its parts beside it, each a jump to its heading; the screens before it have no list', async () => {
    setup()
    await screen.findByRole('heading', { name: 'Tell me about yourself' })
    expect(screen.queryByRole('navigation', { name: 'Sections' })).toBeNull()
    await toReview()
    const links = within(screen.getByRole('navigation', { name: 'Sections' })).getAllByRole('link')
    expect(links.map((l) => l.textContent)).toEqual(['You', 'Titles', 'What matters to you', 'Search', 'CV', 'Where to find employers'])
    for (const l of links) expect(document.getElementById(l.getAttribute('href')!.slice(1))).not.toBeNull()
  })

  it('Save goes straight into the first run', async () => {
    const h = setup()
    await toReview()
    await userEvent.click(screen.getByRole('button', { name: 'Save and start searching' }))
    await waitFor(() => expect(h.onFinish).toHaveBeenCalledWith(true))
    expect(h.call.mock.calls.map((c) => c[0])).not.toContain('find_jobs') // the app starts it
  })

  it('a draft that fails asks for the CV at the review, and then the first run starts', async () => {
    const h = setup({ draft_cv: () => { throw new Error('no') } })
    await userEvent.click(await screen.findByRole('button', { name: 'Drop relevant documents here (CV or LinkedIn PDF)' }))
    await screen.findByText('cv.pdf')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Go on without a draft' }))
    await screen.findByRole('heading', { name: 'Check your answers' })
    expect(screen.getByRole('button', { name: 'Save and start searching' })).toBeDisabled()
    expect(screen.getByText(/Your CV is needed/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Your CV'), { target: { value: '# Ada' } })
    await userEvent.click(screen.getByRole('button', { name: 'Save and start searching' }))
    await waitFor(() => expect(h.onFinish).toHaveBeenCalledWith(true))
  })

  it('shows the splash until it knows about Claude, and then no connect step when connected', async () => {
    setup()
    expect(screen.getByRole('status', { name: 'Starting The other door' })).toBeInTheDocument()
    await screen.findByRole('heading', { name: 'Tell me about yourself' })
    expect(screen.getByLabelText('Step 1 of 3')).toHaveAttribute('aria-current', 'step')
    expect(screen.queryByRole('heading', { name: 'Connect Claude' })).toBeNull()
  })

  it('signed out: connect comes first, before the three steps, and moves on by itself', async () => {
    let answer = doctorReport('out')
    setup({ doctor: () => answer })
    await screen.findByRole('heading', { name: 'Connect Claude' })
    expect(screen.getAllByRole('listitem', { name: /Step \d of 3/ })).toHaveLength(3)
    expect(document.querySelector('.segments [aria-current]')).toBeNull()
    expect(document.querySelectorAll('.segment-done')).toHaveLength(0)
    answer = doctorReport('ok')
    await userEvent.click(screen.getByRole('button', { name: 'Check again' }))
    await screen.findByRole('heading', { name: 'Tell me about yourself' })
    expect(screen.getByLabelText('Step 1 of 3')).toHaveAttribute('aria-current', 'step')
  })

  it('stays on the connect step while a check is on its way', async () => {
    const answers: ((r: unknown) => void)[] = []
    let first = true
    setup({ doctor: () => (first ? ((first = false), doctorReport('out')) : new Promise((r) => answers.push(r))) })
    await screen.findByRole('heading', { name: 'Connect Claude' })
    await userEvent.click(screen.getByRole('button', { name: 'Check again' }))
    expect(screen.getByRole('heading', { name: 'Connect Claude' })).toBeInTheDocument()
    answers[0]?.(doctorReport('out'))
  })

  it('a redo can be left at its first screen', async () => {
    const onCancel = vi.fn()
    setup({}, { profile: saved, onCancel })
    await userEvent.click(await screen.findByRole('button', { name: 'Back' }))
    expect(onCancel).toHaveBeenCalled()
  })

  it('Back from the review keeps the answers and the sources', async () => {
    setup()
    await toReview()
    await userEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(screen.getByRole('heading', { name: 'Tell me about yourself' })).toBeInTheDocument()
    expect(screen.getByText('cv.pdf')).toBeInTheDocument()
  })

  it('installs a missing Chromium quietly, once, and not in the sandbox', async () => {
    for (const environment of ['production', 'staging'] as const) {
      const h = setup({ doctor: doctorReport('ok', false), setup: { outcome: 'ok' } }, { environment })
      await waitFor(() => expect(h.call).toHaveBeenCalledWith('setup', { install: ['chromium'], yes: true }))
      expect(screen.queryByRole('dialog')).toBeNull()
      cleanup()
    }
    const sandboxed = setup({ doctor: doctorReport('ok', false), setup: { outcome: 'ok' } }, { environment: 'sandbox' })
    await screen.findByRole('button', { name: 'Drop relevant documents here (CV or LinkedIn PDF)' })
    await waitFor(() => expect(sandboxed.call.mock.calls.map((c) => c[0])).toContain('doctor'))
    expect(sandboxed.call.mock.calls.map((c) => c[0])).not.toContain('setup')
    // the status call skips the test print: the app asks often
    expect(sandboxed.call).toHaveBeenCalledWith('doctor', { quick: true })
  })

  it('forgets the picked CV files when it closes', async () => {
    const { clearCvSources, unmount } = setup()
    await screen.findByRole('heading', { name: 'Tell me about yourself' })
    expect(clearCvSources).not.toHaveBeenCalled()
    unmount()
    expect(clearCvSources).toHaveBeenCalled()
  })
})
