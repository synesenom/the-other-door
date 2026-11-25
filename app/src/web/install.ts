// Offering to install the phone app (#576). Chromium fires `beforeinstallprompt` once and early, so it is
// kept from the page's start (captureInstallPrompt, called by main.tsx before React renders); iOS Safari
// has no such event, only Share > Add to Home Screen, which the line says in words.
import { useSyncExternalStore } from 'react'

type PromptEvent = Event & { prompt(): Promise<unknown> }
export type InstallOffer = 'prompt' | 'ios' | null

const KEY = 'door.install.dismissed'
let kept: PromptEvent | null = null
let listening = false
const watchers = new Set<() => void>()
const notify = () => watchers.forEach((w) => w())

const onPrompt = (e: Event) => {
  e.preventDefault()
  kept = e as PromptEvent
  notify()
}
const onInstalled = () => {
  kept = null
  notify()
}

export function captureInstallPrompt(): void {
  if (listening) return
  listening = true
  window.addEventListener('beforeinstallprompt', onPrompt)
  window.addEventListener('appinstalled', onInstalled)
}

function subscribe(cb: () => void): () => void {
  watchers.add(cb)
  return () => void watchers.delete(cb)
}

function isStandalone(): boolean {
  return window.matchMedia('(display-mode: standalone)').matches || (navigator as { standalone?: boolean }).standalone === true
}

function isIosSafari(): boolean {
  const ua = navigator.userAgent
  const ios = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)
  return ios && !/CriOS|FxiOS|EdgiOS/.test(ua)
}

function dismissed(): boolean {
  return localStorage.getItem(KEY) === '1'
}

export function dismiss(): void {
  localStorage.setItem(KEY, '1')
  notify()
}

/** The browser's own install dialog; the event can be used once. */
export async function install(): Promise<void> {
  const e = kept
  if (!e) return
  kept = null
  notify()
  await e.prompt()
}

function offer(): InstallOffer {
  if (isStandalone() || dismissed()) return null
  if (kept) return 'prompt'
  return isIosSafari() ? 'ios' : null
}

export function useInstallOffer(): InstallOffer {
  return useSyncExternalStore(subscribe, offer)
}
