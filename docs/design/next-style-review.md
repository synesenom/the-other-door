# Next style: review and changes

An independent review of the next style (`style-guide-next.png`), run on 2026-11-22, looked for what can be
removed, merged or simplified. Each finding below was checked against the code; the chosen change is what
`style-guide-next.png` now shows. Nothing here is in the app yet.

Decisions taken before the review, not reopened: the parchment ground, Young Serif and Figtree, the switch,
the original logo, no underline on quiet buttons, the faded blue `#3D5798` as the accent.

## Changes

1. **One mark for "this opens something".** The arrow (`.go`) and a trailing `…` did the same job. Now:
   the arrow only for an action that leaves the app (Open in browser, Download, the sign-in page); `…` for an
   action that opens a dialog (Status…, Add a job…, Edit…); nothing for an action done in place.
2. **Only the weights the app loads.** The label was set in Figtree 700, which is not bundled, so the browser
   faked it. Labels go back to 600, and the field name moves from 500 to 600: two weights in all, 400 and 600.
3. **Quiet buttons and filters tell apart.** Both were grey words. Unchosen filters are now ink; grey words
   mean only a quiet action.
4. **The black button stays black on hover.** It turned blue, against the rule that blue is never a button
   fill. It turns `ink-muted`, as before.
5. **One way to show what is current.** It was shown five ways (underline, fill, dash, side bar, blue block).
   Now only an underline, for a chosen word (the sidebar, filters, the page list beside Profile and Settings).
   The blue bar no longer marks what is current: clicking a match opens the posting, so no list row is shown as
   open, and the row it came from keeps no fill. The bar stays the logo's own; the two places that still draw
   it as decoration (above the phone's set-up title and above an answer in "Ask about your jobs") are left to
   the change that builds this style.
6. **Heavy rule on the column, not on every card.** The Applications board puts the heavy ink rule under the
   column's head and hairlines between its cards, as the phone layout already does.
7. **Notes, errors and chips: a fill, no outline.** The review warned that without an outline the `surface`
   fill is 1.1:1 on the ground, almost invisible, and proposed plain lines and outlined chips. The owner keeps
   the fill and drops the outline; the fill is `page` (into which `surface` folds, change 8), 1.2:1 on the
   ground, which reads as a shaded strip.
8. **Fewer near-duplicates.**
   - `surface` folds into `page` (once rows lose their fill, notes and chips are what is left, and they take `page`).
   - `paper-muted` (one use) becomes `border`; `on-warning` and `paper-ink` (1.09:1 apart) become one dark ink.
   - One corner radius, 2 px, besides the round ends of bars, the dash and the switch.
   - `score-s` (20) merges into `display-s` (22): list scores take the heading size.
   - `button-height` and `chip-height` (both 32) become one token; the phone's 30/44 overrides of 32/50 go.
   - Two underline offsets (3 px under links and text buttons, 6 px under chosen words), and no extra
     tracking on buttons.
   - Unused tokens and classes go: `content-max-width`, `sidebar-breakpoint` (as a CSS variable),
     `phone-tab-bar-icon`, `cv-panel`, `employer-head`, `employer-list`; the 620 px column used five times
     becomes a token.
9. **Leftover boxes and rules.** The run's summary card gets a heavy rule on top instead of an outline and a
   shadow (the dialog keeps the only shadow); the CV preview and the demo tag lose their boxes; the old
   outline rules of `.secondary` and `.chip` are removed, not overridden. The filter class `.pill` is renamed,
   as it is no longer a pill.
10. **The design README is rewritten where the next style makes it false**: radii, the 44 px controls, the
    hover rules, the secondary's outline, the ink-filled filter, the chip's border, the note's box, the
    selected row, and "quiet only beside a bordered button" (now: only beside the black button).

## Kept as they are

One black button per view; blue words for actions (5.6:1, 7.7:1 in dark); `ink-muted` (4.9:1); a box around
text fields; success, danger and warning as marks only; the spacing scale; body 14 and small 13; the heavy
rule with hairlines.
