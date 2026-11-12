// What the window shows while it starts (the page loading, then the server answering its first call):
// the logo's `d` on the ground and a blue bar under it that grows from the left and shrinks to the right. index.html (the desktop window's
// and the phone app's) holds the same markup inside #root, so it shows before any script runs and
// nothing blinks when React takes over; Splash.test.tsx keeps the three the same.
import { useLayoutEffect, useRef } from 'react'

// When the bar first started (on the document's timeline). A new splash element starts its animation
// over, so the one React puts in place of index.html's, or a splash shown again, would jump back to the
// start; each one instead carries on from this moment, and the bar runs on as one.
let origin: number | null = null

const barAnimations = (el: Element | null): Animation[] => el?.getAnimations?.({ subtree: true }) ?? []

/** Remembers when index.html's bar started; called before React replaces it. */
export function keepSplashTime(el: Element | null = document.querySelector('.splash-dash')): void {
  if (origin !== null) return
  const start = barAnimations(el).find((a) => typeof a.startTime === 'number')?.startTime
  if (typeof start === 'number') origin = start
}

export function Splash() {
  const bar = useRef<HTMLSpanElement>(null)
  useLayoutEffect(() => {
    const el = bar.current
    if (origin === null) {
      // the first bar of this page: remember its start once it has one (the next frame)
      const frame = requestAnimationFrame(() => keepSplashTime(el))
      return () => cancelAnimationFrame(frame)
    }
    for (const a of barAnimations(el)) a.startTime = origin
  }, [])
  return (
    <div className="splash" role="status" aria-label="Starting The other door">
      <svg className="splash-logo" viewBox="0 0 512 512" width="96" height="96" aria-hidden="true">
        <path transform="translate(97.5 452.5) scale(.5 -.5)" d="M533 185Q533 149 544.0 120.5Q555 92 592 87Q604 86 604 74V41Q604 27 589 27Q540 27 507.5 21.5Q475 16 451.5 7.5Q428 -1 405 -11Q401 -13 398 -13H396Q393 -13 393 -10Q395 13 397.5 35.0Q400 57 404 79Q399 66 382.5 44.0Q366 22 334.5 4.5Q303 -13 252 -13Q218 -13 179.5 1.0Q141 15 107.0 46.0Q73 77 51.5 127.5Q30 178 30 251Q30 344 63.5 401.5Q97 459 150.5 486.0Q204 513 264 513Q340 513 393 466V530Q393 557 389.5 582.0Q386 607 374.0 624.5Q362 642 334 645Q322 646 322 658V692Q322 698 326.0 700.5Q330 703 337 705Q416 731 460.5 757.0Q505 783 525 798Q528 800 530 800H531Q533 800 533 798ZM393 324Q393 371 362.5 404.0Q332 437 282 437Q234 437 207.0 416.0Q180 395 169.5 360.0Q159 325 159 283Q159 187 197.5 131.0Q236 75 297 75Q324 75 344.0 88.5Q364 102 376.5 122.0Q389 142 393 160Z" fill="currentColor"></path>
      </svg>
      <span ref={bar} className="splash-dash" aria-hidden="true"></span>
    </div>
  )
}
