# Analytics: inventory of interactions and branches (desktop app, real Python server)

Sources read: `app/src/renderer/screens/Analytics.tsx`, `PageSections.tsx`, `api.ts` (`StatusSummary`), and Python `commands/status.py` (`standing`, `pass_rates`, `pipeline`), `core/tracker.py` (`standings`).

The screen is read only: one `status_summary` {} call on opening, no action changes anything. Not on the phone.

## Frame
- Sidebar button "Analytics" opens `heading level 1 "Analytics"`, a list of parts on the right. — ✓ the applications follow the ledger
- A failed `status_summary` is said nowhere: the headings of what loaded only. — unit: `app/src/renderer/screens/Analytics.test.tsx` (a failed read shows no error and no section)

## Applications (`region "Applications"`, only when the summary has a `standing`)
- Interview rate (`pass_rates.application` with `decided` > 0): `display-s` "<rate>%" and "of your applications with an outcome (an interview, a rejection or no reply) led to an interview: <passed> of <decided>, likely between <low>% and <high>%." Before any answer: the muted line "Your interview rate shows here once an application has an outcome." — ✓ the applications follow the ledger (75%, 3 of 4); unit: `Analytics.test.tsx`; preview: `preview.test.tsx`
- `group "Your matches"` (when there are matches): heading "Your matches · <applied + prepared + unapplied>", `img` named "Applied <n>, Prepared, not sent <n>, Not yet <n>" (parts with 0 left out), a legend row each; "And <n> you set aside as not for me." when any were discarded. — ✓ the same journey (Applied 5, Prepared, not sent 1, Not yet 9); unit: `Analytics.test.tsx`
- `group "Your applications"` (when any were sent): heading "Your applications · <sent>", `img` named "Offer <n>, Interviewing <n>, Waiting for an answer <n>, Rejected or no answer <n>" ("Rejected, no answer or withdrawn" when one was withdrawn), a legend row each. — ✓ the same journey (Offer 1, Interviewing 1, Waiting 1, Rejected or no answer 2); unit: `Analytics.test.tsx`
- No matches and nothing sent: one muted line "Your applications show here once you have matches." — unit: `Analytics.test.tsx`; preview: `preview.test.tsx` (empty state)
- No `standing` in the summary: no section, no crash. — unit: `Analytics.test.tsx`

## Claude usage (`region "Claude usage"`)
- Branches (activities, singular, nothing in the window, before any call): — unit: `Analytics.test.tsx`; not covered by a journey, the world's Claude stand-in gives no usage to read
