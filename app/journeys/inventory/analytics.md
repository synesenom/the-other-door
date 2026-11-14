# Analytics: inventory of interactions and branches (desktop app, real Python server)

Sources read: `app/src/renderer/screens/Analytics.tsx`, `PageSections.tsx`, `api.ts` (`StatusSummary`), and Python `commands/status.py` (`_funnel`).

The screen is read only: one `status_summary` {} call on opening, no action changes anything. Not on the phone.

## Frame
- Sidebar button "Analytics" opens `heading level 1 "Analytics"`, a list of parts on the right. — ✓ the funnel follows the ledger
- A failed `status_summary` is said nowhere: the headings of what loaded only. — unit: `app/src/renderer/screens/Analytics.test.tsx` (a failed read shows no error and no section)

## Applications (`region "Applications"`, only when the summary has a `funnel`)
- Funnel with postings > 0: one `img` per stage, name "Scraped: <n>", then "<Label>: <n> of <the stage before>" (Worth a look, Matches, Prepared, Applied, Interview, Offer), each bar that share, no table. — ✓ the funnel follows the ledger (Applied 5 of 6, Interview 3 of 5, Offer 1 of 3); unit: `Analytics.test.tsx` (one bar row per stage; sizes each bar against the stage before it)
- A stage with no label is skipped. — unit: `Analytics.test.tsx` (a stage it has no label for is skipped)
- Nothing applied yet: the bars, the later ones empty. — unit: `Analytics.test.tsx` (something found but nothing applied); preview: `preview.test.tsx` (empty state)
- Nothing scraped: one muted line "Your funnel shows here once jobs are found". — unit: `Analytics.test.tsx` (nothing scraped)
- No `funnel` in the summary: no section, no crash. — unit: `Analytics.test.tsx` (a summary without a funnel)

## Claude usage (`region "Claude usage"`)
- Branches (activities, singular, nothing in the window, before any call): — unit: `Analytics.test.tsx`; not covered by a journey, the world's Claude stand-in gives no usage to read
