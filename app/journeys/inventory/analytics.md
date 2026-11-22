# Analytics: inventory of interactions and branches (desktop app, real Python server)

Sources read: `app/src/renderer/screens/Analytics.tsx`, `Market.tsx`, `PageSections.tsx`, `api.ts` (`StatusSummary`), and Python `commands/status.py` (`pass_rates`), `core/jobs/tracker.py` (`application_outcomes`, `NO_ANSWER_DAYS`).

One `status_summary` {} call on opening, and one `market({save:false})` call from Market. Nothing changes except the two actions in Market (add titles, follow an employer). Not on the phone.

## Frame
- Sidebar button "Analytics" opens `heading level 1 "Analytics"`, a list of parts on the right. — ✓ the interview rate follows the ledger
- A failed `status_summary` is said nowhere: the headings of what loaded only. — unit: `app/src/renderer/screens/Analytics.test.tsx` (a failed read shows no error and no section)

## Applications (`region "Applications"`, only when the summary has `pass_rates`)
- Interview rate (`pass_rates.application` with `decided` > 0): `display-s` "<rate>%" and "of your applications with an outcome (an interview, a rejection or no reply) led to an interview: <passed> of <decided>, likely between <low>% and <high>%." Before any outcome (nothing sent included): the muted line "Your interview rate shows here once an application has an outcome." — ✓ the interview rate follows the ledger (75%, 3 of 4); unit: `Analytics.test.tsx`; preview: `preview.test.tsx`
- By score (`pass_rates_by_score`, #90, only under a shown rate): two `small` lines, "Best-scored matches: <passed> of <decided> led to an interview, likely between <low>% and <high>%." and the same for "Matches near your "How close a match to show" setting"; when `reading` is `near_min_lower`, the line "These led to an interview less often: consider raising that setting in Profile."; nothing when the server sends null. — unit: `Analytics.test.tsx`
- Nothing else: no bar of where each application stands (the Applications board's columns) and no split of the matches (the Matches list). — unit: `Analytics.test.tsx`; ✓ the same journey
- No `pass_rates` in the summary: no section, no crash. — unit: `Analytics.test.tsx`

## Claude usage (`region "Claude usage"`, `status_summary`'s `cost`, `core/usage.cost`)
The world's stand-in claude prices each answer (`COST_USD` in `app/test/world/claude.py`: a scoring chunk $0.02, a title translation and a Market grouping $0.01, anything else $0.03; a failed call nothing), so a find in the world leaves a usage log to read.
- Nothing yet (no call weighed, `cost` null): the muted line "What Claude's work costs shows here after your first search." — ✓ Claude usage: nothing before the first search, then what the search cost; unit: `Analytics.test.tsx`
- A plan reading only (calls that reported the plan's windows but no `total_cost_usd`): `cost` stays null, the same line. — unit: `tests/core/test_usage_unit.py` (cost is None without a weight)
- A week of calls: "≈ $<total>", the line "You don't pay this. Your Claude plan covers it. The last 7 days, estimated at API prices.", "About $<find> a search, $<prepare> an application" (each only when it can be sized), one bar (`img`, labelled with each activity's share), and per activity "<label> · <count> <what it did>" with its dollars and, when it has more than one, its features with theirs. — ✓ the same journey (≈ $0.04; $0.03 a search; Finding jobs · 3 postings scored, Scoring postings $0.02, Translating job titles $0.01; Everything else · 1 other request); unit: `Analytics.test.tsx`
- Singular counts ("1 other request", "1 application prepared"). — ✓ the same journey ("1 other request"); unit: `Analytics.test.tsx`
- Nothing in the last 7 days (older calls only): "Nothing in the last 7 days", no bar, no list. — unit: `Analytics.test.tsx`
- Opening Analytics reads the summary and starts Market at once: a Market grouping call can land before or after the read, so what "Everything else" shows on that opening may lag one call; the next opening reads it all.

## Market (`region "Market"`, `Market.tsx`, always the last section)
- Opening Analytics calls `market({save:false})` once, with the status "Counting the ads (new skill names may take one short Claude call)…" (timeout 180 s). Never asked again while the screen stays open. — ✓ counts the ads when Analytics opens, once, and writes no report
- Error: said nowhere, Market and its link left out (principle 9: a read-only section the page stands without; a malformed `companies.json`, an invalid config, a timeout). — ✓ a report that failed is said nowhere and Market is left out (principle 9); unit: `Market.test.tsx`
- No ads read (`skills` empty): one muted line "The market shows here once ads are read." — unit: `Market.test.tsx`; preview: `preview.test.tsx` (empty state)
- Done view: a muted line "What the ads ask for most." and the first 8 skills, each `listitem "<skill>, in your CV|not in your CV"` "<skill> · NN% of the ads", with the check (`skill-fits`) or the cross (`skill-gap`) of a posting's skills. No buttons. — ✓ counts the ads when Analytics opens, once, and writes no report
- `counts`, `near_misses`, `uncovered_titles`, `companies` and `warning` are not shown.
- Side effect even with `save:false`: when new skill names were grouped, `jobs/skill_aliases.json` is written (under the ledger lock); no `jobs/market/report-*.md`. — ✓ counts the ads when Analytics opens, once, and writes no report
