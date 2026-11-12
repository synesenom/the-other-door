// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDoor } from '../testing'
import { SignIn } from './SignIn'

afterEach(cleanup)

async function show(email?: string) {
  const h = mockDoor({})
  const onDone = vi.fn()
  render(<SignIn email={email} onDone={onDone} />)
  await act(async () => {})
  const push = async (s: unknown) => act(async () => h.pushLogin(s))
  return { ...h, onDone, push }
}

describe('SignIn', () => {
  it('starts the sign-in with the email, and only on a click', async () => {
    const { claudeLogin } = await show('ada@example.com')
    expect(claudeLogin.start).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Sign in with Claude' }))
    expect(claudeLogin.start).toHaveBeenCalledWith('ada@example.com')
  })

  it('while waiting: says to finish in the browser, the page again once claude printed it, and Cancel', async () => {
    const { claudeLogin, push } = await show()
    await push({ state: 'waiting', canOpen: false })
    expect(screen.getByRole('status')).toHaveTextContent('Finish signing in in your browser')
    expect(screen.queryByRole('button', { name: 'Sign in with Claude' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Open the sign-in page again' })).toBeDisabled()
    await push({ state: 'waiting', canOpen: true })
    await userEvent.click(screen.getByRole('button', { name: 'Open the sign-in page again' }))
    expect(claudeLogin.openPage).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(claudeLogin.cancel).toHaveBeenCalled()
  })

  it('the code box only after "The page showed a code?", and it sends what was typed', async () => {
    const { claudeLogin, push } = await show()
    await push({ state: 'waiting', canOpen: true })
    expect(screen.queryByLabelText('Sign-in code')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'The page showed a code?' }))
    await userEvent.type(screen.getByLabelText('Sign-in code'), 'code#state1')
    await userEvent.click(screen.getByRole('button', { name: 'Send code' }))
    expect(claudeLogin.sendCode).toHaveBeenCalledWith('code#state1')
  })

  it('a code main refuses is said so', async () => {
    const { claudeLogin, push } = await show()
    claudeLogin.sendCode.mockResolvedValueOnce({ ok: false, error: 'That is not a sign-in code.' } as never)
    await push({ state: 'waiting', canOpen: true })
    await userEvent.click(screen.getByRole('button', { name: 'The page showed a code?' }))
    await userEvent.type(screen.getByLabelText('Sign-in code'), 'x y')
    await userEvent.click(screen.getByRole('button', { name: 'Send code' }))
    expect(screen.getByRole('alert')).toHaveTextContent('That is not a sign-in code.')
  })

  it('done: hands over to doctor', async () => {
    const { onDone, push } = await show()
    await push({ state: 'done' })
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('done but doctor still does not see it once it answered: says so, with Try again', async () => {
    const h = mockDoor({})
    let answer!: () => void
    const onDone = vi.fn(() => new Promise<void>((resolve) => (answer = resolve)))
    render(<SignIn onDone={onDone} />)
    await act(async () => {})
    await act(async () => h.pushLogin({ state: 'done' }))
    expect(screen.getByRole('status')).toHaveTextContent('Checking the sign-in…')
    await act(async () => answer())
    expect(screen.getByRole('alert')).toHaveTextContent("claude said the sign-in worked, but The other door still can't see the sign-in.")
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('a done from before this screen opened is not passed on again (doctor already said signed out)', async () => {
    const h = mockDoor({})
    h.claudeLogin.state.mockResolvedValueOnce({ state: 'done' })
    const onDone = vi.fn()
    render(<SignIn onDone={onDone} />)
    await act(async () => {})
    expect(onDone).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent("The other door still can't see the sign-in")
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('a failure says why, with Try again', async () => {
    const { claudeLogin, push } = await show()
    await push({ state: 'failed', message: 'Request failed with status code 400' })
    expect(screen.getByRole('alert')).toHaveTextContent("The sign-in didn't go through: Request failed with status code 400")
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(claudeLogin.start).toHaveBeenCalled()
  })

  it('a timeout says so, with Try again', async () => {
    const { push } = await show()
    await push({ state: 'timeout' })
    expect(screen.getByRole('alert')).toHaveTextContent('waited five minutes')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('picks up a sign-in already waiting when it opens', async () => {
    const h = mockDoor({})
    h.claudeLogin.state.mockResolvedValueOnce({ state: 'waiting', canOpen: true })
    render(<SignIn onDone={() => {}} />)
    await act(async () => {})
    expect(screen.getByRole('status')).toHaveTextContent('Finish signing in')
  })

  it('an old failure is not shown again when it opens', async () => {
    const h = mockDoor({})
    h.claudeLogin.state.mockResolvedValueOnce({ state: 'failed', message: 'old' })
    render(<SignIn onDone={() => {}} />)
    await act(async () => {})
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByRole('button', { name: 'Sign in with Claude' })).toBeInTheDocument()
  })

  it('stops listening when it closes', async () => {
    const h = mockDoor({})
    const off = vi.fn()
    h.claudeLogin.onState.mockImplementationOnce(() => off)
    const { unmount } = render(<SignIn onDone={() => {}} />)
    await act(async () => {})
    expect(off).not.toHaveBeenCalled()
    unmount()
    expect(off).toHaveBeenCalledTimes(1)
  })
})
