# Analytics: inventory of interactions and branches (desktop app, real Python server)

Sources read: `app/src/renderer/screens/Analytics.tsx`, `PageSections.tsx`, `api.ts` (`StatusSummary`), and Python `commands/status.py` (`_funnel`).

The screen is read only: one `status_summary` {} call on opening, no action changes anything. Not on the phone.

## Frame
- Sidebar button "Analytics" opens `heading level 1 "Analytics"`, a list of parts on the right. — ✓ the funnel follows the ledger
- A failed `status_summary` is said nowhere: the headings of what loaded only. — unit: `app/src/renderer/screens/Analytics.test.tsx` (a failed read shows no error and no section)

## Applications (`region "Applications"`, only when the summary has a `funnel`)
- Funnel with matches > 0: the line "<n> matches. Each stage against the one before it." (`postings` and `applicable` not shown: what was scraped includes unrelated jobs, #87), then one `img` per stage after the matches, name "<Label>: <n> of <the stage before>" (Prepared against the matches, then Applied, Interview, Offer), each bar that share; each row shows "<n> of <the stage before>" and the share as a percentage (none when the stage before is 0), no table. — ✓ the funnel follows the ledger (Applied 5 of 6, Interview 3 of 5, Offer 1 of 3); unit: `Analytics.test.tsx` (the matches in a line, one bar row per later stage; sizes each bar against the stage before it); preview: `preview.test.tsx` ("9 of 34" and the line)
- A stage with no label is skipped. — unit: `Analytics.test.tsx` (a stage it has no label for is skipped)
- Nothing applied yet: the bars, the later ones empty. — unit: `Analytics.test.tsx` (something found but nothing applied)
- No matches (nothing scraped, or nothing scraped matched): one muted line "Your funnel shows here once you have matches". — unit: `Analytics.test.tsx` (nothing scraped; jobs scraped but none a match); preview: `preview.test.tsx` (empty state)
- No `funnel` in the summary: no section, no crash. — unit: `Analytics.test.tsx` (a summary without a funnel)

## Claude usage (`region "Claude usage"`)
- Branches (activities, singular, nothing in the window, before any call): — unit: `Analytics.test.tsx`; not covered by a journey, the world's Claude stand-in gives no usage to read
