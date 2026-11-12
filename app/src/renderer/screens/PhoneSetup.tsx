// "Set up your phone" (issue 444): a Cloudflare quick tunnel, a QR code to scan, then adding door to the
// home screen, for someone who never opens a terminal. Everything goes through the phone tools
// (phone_start, pair_phone, phone_status); the pairing code is only ever inside the QR image.
import { useEffect, useRef, useState } from 'react'
import { AppName, named } from './AppName'
import { call, errorText } from '../api'
import { Dialog } from './Dialog'
import { Spinner } from './Spinner'

export interface PhoneStatus {
  running: boolean
  connection?: 'tailscale' | 'cloudflare'
  address?: string
  lasting?: boolean
  devices: { device: string; paired_at: string | null; last_seen: string | null }[]
  web_built: boolean
  tailscale_installed: boolean
}
type Qr = { device: string; qr_svg: string; expires_at: string }
/** One phone: always this name, so pairing again replaces the phone paired before. */
const DEVICE = 'My phone'
type Step = 'how' | 'pair' | 'home'

const failure = (data: unknown): string | null =>
  data && typeof data === 'object' && typeof (data as { error?: unknown }).error === 'string' ? (data as { error: string }).error : null

/** The QR code's SVG as an image address (shown with <img>: no markup goes into the page). */
const qrSrc = (svg: string) => `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svg)))}`

export function PhoneSetup({ onClose, start = 'how', pollMs = 2000 }: { onClose: () => void; start?: Step; pollMs?: number }) {
  const [step, setStep] = useState<Step>(start)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<PhoneStatus | null>(null)
  const [qr, setQr] = useState<Qr | null>(null)
  const [expired, setExpired] = useState(false)

  const begin = async () => {
    setBusy('Starting The other door for your phone…')
    setError(null)
    try {
      const r = await call<PhoneStatus | { error: string }>('phone_start', { connection: 'cloudflare' })
      const why = failure(r)
      if (why) return setError(why)
      setStatus(r as PhoneStatus)
      setStep('pair')
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(null)
    }
  }

  const showQr = async () => {
    setBusy('Making a code…')
    setError(null)
    try {
      const r = await call<Qr | { error: string }>('pair_phone', { device: DEVICE })
      const why = failure(r)
      if (why) return setError(why)
      setQr(r as Qr)
      setExpired(new Date((r as Qr).expires_at).getTime() <= Date.now())
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(null)
    }
  }

  // The pair step makes its code at once: there is nothing to type first. Once per visit to the step.
  const asked = useRef(false)
  useEffect(() => {
    if (step !== 'pair') {
      asked.current = false
      return
    }
    if (asked.current) return
    asked.current = true
    void showQr()
  }, [step])

  // While the QR code shows: wait for the phone to appear, and for the code to run out.
  useEffect(() => {
    if (step !== 'pair' || !qr || expired) return
    let live = true
    // Compared by date: a phone pairing again after a restart keeps its name.
    const pairedAt = new Map((status?.devices ?? []).map((d) => [d.device, d.paired_at]))
    const timer = setInterval(async () => {
      if (new Date(qr.expires_at).getTime() <= Date.now()) {
        if (live) setExpired(true)
        return
      }
      try {
        const s = await call<PhoneStatus>('phone_status')
        if (live && s.devices.some((d) => d.device === qr.device && d.paired_at !== pairedAt.get(d.device))) setStep('home')
      } catch {
        // keep waiting
      }
    }, pollMs)
    return () => {
      live = false
      clearInterval(timer)
    }
  }, [step, qr, expired, status, pollMs])

  // A step's button goes away with the step: the focus goes to Close, or Escape would no longer reach the dialog.
  const close = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (document.activeElement === document.body) close.current?.focus()
  })

  return (
    <Dialog title="Set up your phone" onClose={onClose}>
      {step === 'how' && (
        <div className="phone-step">
          <p className="body"><AppName /> on your phone is this app, served by this computer. There is nothing to install: scan a code and it works anywhere while this computer is on.</p>
          <p className="small muted">When this computer restarts, set this up again and scan a new code. What you see on your phone passes through Cloudflare, which could read it on the way.</p>
          {busy && <Spinner message={busy} />}
          {error && (
            <p role="alert" className="small error">
              {named(error)}
            </p>
          )}
          <div className="actions">
            <button type="button" className="quiet" onClick={onClose}>
              Cancel
            </button>
            <button type="button" className="primary" disabled={Boolean(busy)} onClick={() => void begin()}>
              Continue
            </button>
          </div>
        </div>
      )}

      {step === 'pair' && (
        <div className="phone-step">
          {status?.address && (
            <p className="small muted">
              {status.lasting
                ? `Serving at ${status.address}, an address that stays the same.`
                : `Serving at ${status.address}. This address changes when this computer restarts.`}
            </p>
          )}
          {!qr ? (
            // the code is being made; if that failed, the error says why and this tries again
            error && !busy ? (
              <div className="actions">
                <button type="button" className="primary" onClick={() => void showQr()}>
                  Try again
                </button>
              </div>
            ) : null
          ) : expired ? (
            <>
              <p className="body">This code has expired. Make a new one and scan it within five minutes.</p>
              <div className="actions">
                <button type="button" className="primary" onClick={() => void showQr()}>
                  New code
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="body">Point your phone's camera at the code and open the link it shows. It works once, for five minutes.</p>
              <img className="phone-qr" src={qrSrc(qr.qr_svg)} alt="QR code that pairs your phone" />
              <Spinner message="Waiting for your phone…" />
            </>
          )}
          {busy && <Spinner message={busy} />}
          {error && (
            <p role="alert" className="small error">
              {named(error)}
            </p>
          )}
          <div className="actions">
            <button ref={close} type="button" className="quiet" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      )}

      {step === 'home' && (
        <div className="phone-step">
          <h3 className="display-s">Add The other door to your home screen</h3>
          <p className="body">Your phone is paired. So that <AppName /> opens like an app:</p>
          <ul className="phone-home">
            <li className="body">
              <strong>Android:</strong> in Chrome, open the menu (⋮) and tap <strong>Install app</strong>.
            </li>
            <li className="body">
              <strong>iPhone:</strong> in Safari, tap Share, then <strong>Add to Home Screen</strong>.
            </li>
          </ul>
          {!status?.lasting && <p className="small muted">When this computer restarts, set this up again and scan the new code. The address changes with it, so add it again to your home screen and remove the old one.</p>}
          <div className="actions">
            <button type="button" className="primary" onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      )}
    </Dialog>
  )
}
