// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ImportDialog } from './ImportDialog'
import { mockDoor } from '../testing'

afterEach(cleanup)

const shown = { id: 'manual.ab12', title: 'Data Analyst', company: 'Acme', location: 'Aarhus', status: 'unapplied' }
const scored = { job_id: 'manual.ab12', path: '/x/y.json', replaced: false, score: 0.82, score_reason: 'Good SQL fit.' }

function open(handlers: Record<string, unknown> = {}) {
  const h = mockDoor({ import_posting: scored, show: shown, ...handlers })
  const onOpen = vi.fn()
  const onClose = vi.fn()
  render(<ImportDialog onClose={onClose} onOpen={onOpen} />)
  return { ...h, onOpen, onClose }
}

describe('ImportDialog', () => {
  it('Link sends only the url and the fields that were filled', async () => {
    const { call } = open()
    await userEvent.type(screen.getByLabelText('Link'), 'https://example.com/job/1')
    await userEvent.type(screen.getByLabelText('Company (optional)'), 'Acme')
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))
    await waitFor(() => expect(call).toHaveBeenCalledWith('import_posting', { url: 'https://example.com/job/1', company: 'Acme' }))
  })

  it('Import waits for a link', () => {
    open()
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled()
  })

  it('Paste text needs the text, a title and a company', async () => {
    const { call } = open()
    await userEvent.click(screen.getByRole('button', { name: 'Paste text' }))
    const go = screen.getByRole('button', { name: 'Import' })
    await userEvent.type(screen.getByLabelText('Ad text'), 'We need an analyst')
    expect(go).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Title'), 'Data Analyst')
    expect(go).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Company'), 'Acme')
    expect(go).toBeEnabled()
    await userEvent.click(go)
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith('import_posting', { text: 'We need an analyst', title: 'Data Analyst', company: 'Acme' }),
    )
  })

  it('says it is reading and scoring while it waits', async () => {
    let release: (v: unknown) => void = () => {}
    open({ import_posting: () => new Promise((r) => (release = r)) })
    await userEvent.type(screen.getByLabelText('Link'), 'https://example.com/1')
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Reading and scoring the ad…')
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled()
    release(scored)
    await screen.findByText('Good SQL fit.')
  })

  it('shows title, company, score and reason on success, and Open hands over the id', async () => {
    const { onOpen, call } = open()
    await userEvent.type(screen.getByLabelText('Link'), 'https://example.com/1')
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))
    expect(await screen.findByText('Data Analyst')).toBeInTheDocument()
    expect(screen.getByText(/Acme/)).toBeInTheDocument()
    expect(screen.getByText('0.82')).toBeInTheDocument()
    expect(screen.getByText('Good SQL fit.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Open' }))
    expect(onOpen).toHaveBeenCalledWith('manual.ab12')
    expect(call).not.toHaveBeenCalledWith('prepare', expect.anything())
  })

  it('an unscored ad says so in words, with the technical reason folded away', async () => {
    open({ import_posting: { ...scored, score: null, score_reason: null, score_error: 'profile/config.json not found: /Users/x/profile' } })
    await userEvent.type(screen.getByLabelText('Link'), 'https://example.com/1')
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))
    expect(await screen.findByText('Not scored yet. It is scored on the next run.')).toBeInTheDocument()
    const why = screen.getByText('Why?')
    expect(why.tagName).toBe('SUMMARY')
    expect(why.closest('details')).not.toHaveAttribute('open')
    expect(why.closest('details')).toHaveTextContent('profile/config.json not found')
  })

  it('a duplicate offers to import again with force', async () => {
    let first = true
    const { call } = open({
      import_posting: () => {
        if (first) {
          first = false
          throw { message: "a posting with id 'manual.ab12' is already stored at /x/y.json — pass force to replace it" }
        }
        return scored
      },
    })
    await userEvent.type(screen.getByLabelText('Link'), 'https://example.com/1')
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))
    expect(await screen.findByText(/already imported/i)).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/manual\.ab12|\/x\/y/)
    await userEvent.click(screen.getByRole('button', { name: 'Import again anyway' }))
    await waitFor(() => expect(call).toHaveBeenCalledWith('import_posting', { url: 'https://example.com/1', force: true }))
    await screen.findByText('Good SQL fit.')
  })

  it('shows any other error as an alert and stays open', async () => {
    open({
      import_posting: () => {
        throw { message: 'the page needs a login: paste the text instead' }
      },
    })
    await userEvent.type(screen.getByLabelText('Link'), 'https://example.com/1')
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('paste the text instead')
    expect(screen.queryByRole('button', { name: 'Import again anyway' })).toBeNull()
  })

  it('Cancel leaves without a call', async () => {
    const { call, onClose } = open()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onClose).toHaveBeenCalled()
    expect(call).not.toHaveBeenCalled()
  })
})
