# Analytics: inventory of interactions and branches (desktop app, real Python server)

Sources read: `app/src/renderer/screens/Analytics.tsx`, `Market.tsx`, `PageSections.tsx`, `api.ts` (`StatusSummary`), and Python `commands/status.py` (`pass_rates`), `core/tracker.py` (`application_outcomes`, `NO_ANSWER_DAYS`).

One `status_summary` {} call on opening, and one `market({save:false})` call from Market. Nothing changes except the two actions in Market (add titles, follow an employer). Not on the phone.

## Frame
- Sidebar button "Analytics" opens `heading level 1 "Analytics"`, a list of parts on the right. — ✓ the interview rate follows the ledger
- A failed `status_summary` is said nowhere: the headings of what loaded only. — unit: `app/src/renderer/screens/Analytics.test.tsx` (a failed read shows no error and no section)

## Applications (`region "Applications"`, only when the summary has `pass_rates`)
- Interview rate (`pass_rates.application` with `decided` > 0): `display-s` "<rate>%" and "of your applications with an outcome (an interview, a rejection or no reply) led to an interview: <passed> of <decided>, likely between <low>% and <high>%." Before any outcome (nothing sent included): the muted line "Your interview rate shows here once an application has an outcome." — ✓ the interview rate follows the ledger (75%, 3 of 4); unit: `Analytics.test.tsx`; preview: `preview.test.tsx`
- Nothing else: no bar of where each application stands (the Applications board's columns) and no split of the matches (the Matches list). — unit: `Analytics.test.tsx`; ✓ the same journey
- No `pass_rates` in the summary: no section, no crash. — unit: `Analytics.test.tsx`

## Claude usage (`region "Claude usage"`)
- Branches (activities, singular, nothing in the window, before any call): — unit: `Analytics.test.tsx`; not covered by a journey, the world's Claude stand-in gives no usage to read

## Market (`region "Market"`, `Market.tsx`, always the last section)
- Opening Analytics calls `market({save:false})` once, with the status "Counting the ads (new skill names may take one short Claude call)…" (timeout 180 s). Never asked again while the screen stays open. — ✓ counts the ads when Analytics opens, once, and writes no report
- Error: `p.field-error` role alert, `named()` text (a malformed `companies.json`, an invalid config, a timeout). — ✓ a report that failed says why; unit: `Market.test.tsx`
- No ads read (`skills` empty): one muted line "The market shows here once ads are read." — unit: `Market.test.tsx`; preview: `preview.test.tsx` (empty state)
- Done view: a muted line "What the ads ask for most." and the first 8 skills, each `listitem "<skill>, in your CV|not in your CV"` "<skill> · NN% of the ads", with the check (`skill-fits`) or the cross (`skill-gap`) of a posting's skills. No buttons. — ✓ counts the ads when Analytics opens, once
- `counts`, `near_misses`, `uncovered_titles`, `companies` and `warning` are not shown.
- Side effect even with `save:false`: when new skill names were grouped, `jobs/skill_aliases.json` is written (under the ledger lock); no `jobs/market/report-*.md`. — ✓ counts the ads when Analytics opens, once
