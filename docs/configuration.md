# Configuration

Your profile lives in `profile/` (gitignored, never committed): `config.json`, `cv.md`,
and the LaTeX templates. Only two files carry your data: `config.json` and
`cv.md`. The templates (`cv.template.tex`, `cover-letter.template.tex`) hold the styling —
fonts, colours, margins and the macros the tailor uses — and nothing personal; the tailor
writes the whole document body from `cv.md` and `config.json` for every application, so
there is nothing to keep in sync by hand. Edit a template only to restyle the PDFs; keep its
`babel` line (English first, French available), which a French application relies on, and the
fonts it loads from `<<fonts>>/` (`compile` puts the profile's `fonts/` folder there: Figtree and Young Serif,
under the SIL Open Font License). A template copied before French was supported still works: the tailor
then sets the French spacing by hand.

Setting up never overwrites a template already in `profile/`, so a newer default reaches an existing
profile only when you take it: delete `profile/cv.template.tex` and `profile/cover-letter.template.tex`
(or copy yours aside), then run `./door init` (or Settings → Set up again in the app), which copies the
missing files, the `fonts/` folder included, from `profile.example/`. The next prepare uses them.

## Where your data lives

`profile/`, `jobs/`, `backups/` and `upskill/` live in the checkout by default. To keep them
elsewhere (outside the git checkout, or because the code sits in a read-only install), set the
environment variable `DOOR_HOME` to a folder before running *The other door*:

```bash
DOOR_HOME=~/door-data ./door init --name "Jane Doe" ...
```

It is an environment variable, not a config key, because it says where `config.json` is. Unset
or empty, everything stays where it is today. What moves: `profile/`, `jobs/`, `backups/`,
`upskill/`, and the `.mcp.json` the tailor session uses (generated there for the Python
running *The other door*, and rewritten when that changes; the checkout's own `.mcp.json` is used when
`DOOR_HOME` is unset). What does not: `profile.example/`, `.claude/` (the agents) and `src/`,
which ship with the code. Relative paths in `config.json` (`cv_content`, `cv_template`,
`cover_letter_template`, `photo`, e.g. `profile/cv.md`) resolve from `DOOR_HOME`. `./door doctor` prints
`data folder: <path>`. Register the MCP server for Claude Code with the same variable in its
`env` if you use it with a custom folder.

## Creating the profile

`/onboard` in a Claude Code conversation creates it (and your CV and keywords) from
your CV and public pages. From a shell:

```bash
./door init
```

`init` copies `profile.example/` into `profile/` (skipping files that already exist, and
never its example `cv.md` or `story_bank.md`: the CV is the one you draft or write, the story bank starts
empty and fills from your own CV) when you
save. It reads `name`, `email`, `location`, `languages` (the job-ad languages to consider) and
`role_targets` from your sources and asks only for what it could not find; `min_score` and `exclude` are
not asked (`init --set`, or Profile in the app). Questions with a fixed set of answers are lists you
pick from with the arrow keys (space ticks a box in a multi-choice list): `location` from
the known cities, or "Other…" to type one, then `languages`. The job boards are not asked:
`init` names the ones your city's country has (Copenhagen: Denmark's boards plus the
worldwide ones; a city in no known country: only the worldwide ones, with a note pointing to
[Adding a site or a country](adding-a-site.md)). It validates the
result before writing `profile/config.json` and never overwrites an existing profile
without asking. `/onboard` does the same in a conversation.

`find` searches every job board serving your `location`'s country (for Denmark `jobindex`, `jobmaskinen`,
`thehub` and `workable`; elsewhere `workable`), and asks the discovery sources serving it
(LinkedIn anywhere, profession.hu in Hungary, Jobbsafari in Sweden, HelloWork in France) which employers hire, so it works right away; no site
needs a login, and there is no setting for it (`find --boards a,b` narrows one run). The employers' own feeds (`greenhouse`, `lever`, `teamtailor`,
`successfactors`, …) are not listed in the config: `follow` finds them for the employers the
boards and LinkedIn show, and `./door companies add` follows more (see
[Following companies directly](#following-companies-directly)); `collect` reads every followed one.

`init` with flags asks nothing and changes only the keys you name — the shell form of
the `init_profile` tool a conversation uses:

```bash
./door init --name "Jane Doe" --location Copenhagen --role-targets "financial controller, head of finance"
./door init --search-keywords "financial controller, finance manager, controller"   # one key, in place
./door init --set remote=hybrid --set max_age_days=14
```

`--set KEY=VALUE` takes any config key; the value is JSON when it parses (a list, a number,
`true`) and a plain string otherwise. Every form validates before writing. A `config.json`
that does not validate can always be saved over: its invalid keys you do not set again are
removed, and named (`Removed from profile/config.json, as it was not valid: …`).

Interactive `init` also drafts `profile/cv.md` from your existing CV and public pages and
proposes `search_keywords` (see [*The other door* from the terminal](manual-cli.md#walkthrough)).
`enrich` (`/expand`) adds to the CV from public URLs later.

To start by hand instead: `cp -r profile.example/ profile/` and edit `profile/config.json`.

## Following companies directly

The per-company feeds read an employer's whole careers board at the source, but only for the
employers you follow. They are listed in one file, `profile/companies.json` (gitignored, like
the rest of `profile/`; `profile.example/companies.json` shows the shape). *The other door* finds the feed
for you:

```bash
./door companies add Trustpilot "Novo Nordisk" careers.trackman.com   # detect each one's feed and follow it
./door companies add Trustpilot --dry-run                              # ...or only show what it would record
./door companies                   # the list: ✓ followed, ✗ unfollowable, ? unresolved, · dormant
./door companies list --status unresolved --found-via linkedin
./door companies why Trustpilot    # feed, status, reason, evidence, dates, postings from it
./door companies remove Trustpilot # unfollow
```

`add` takes a name, a careers link or a career host and uses only public signals: the
link's own shape (`job-boards.greenhouse.io/<board>`), the host's DNS name (a CNAME to
Teamtailor, Recruitee or SAP SuccessFactors), its careers page (one request; given an employer's home page or a page on its site instead, it follows the careers links it finds there, up to two hops, and a deep link falls back to the site's home page) and, for a bare name, each feed's public endpoint with the name's likely slugs
(Greenhouse, Lever US then EU, Ashby, Recruitee, Pinpoint, Teamtailor, Workable) and its likely career
hosts (`careers.<name>.com`, `jobs.<name>.com`, and on the domain of your `location`'s country the career words of its languages: `karriere.<name>.dk` in Denmark, `karrier.<name>.hu` in Hungary). The slugs leave out company forms and country names ("Novo Nordisk A/S", "Wizz Air Hungary Zrt."). A feed found is recorded as followed (nothing else to configure:
`collect` reads it); a platform *The other door* can't follow (HR-ON; a Phenom front end whose Workday site lists nothing publicly) is recorded as
unfollowable with the reason and its `refusal`, and a miss as unresolved with the slugs tried (a Workday tenant becomes a `career_sites`
feed). Following an employer already on the list updates it; a later miss never unfollows it.
`--no-probe` uses only the link's shape and DNS. In a conversation: "add Trustpilot", "why don't I
follow Danske Bank?", "which companies do I follow?" (the `add_company`, `why_company`,
`list_companies` and `remove_company` tools). `follow` adds to the same list, recording every
employer that `search` and `discover` queued (see [How it works](how-it-works.md#the-five-steps)).

### `profile/companies.json`

```json
{"version": 1, "companies": [
  {"name": "BEC Financial Technologies",
   "feed": {"platform": "hr_manager", "id": "bec"},
   "status": "followed",
   "reason": null,
   "found_via": "manual",
   "evidence": "HR-Manager feed bec lists open jobs",
   "first_seen": "2026-10-13T09:00:00+00:00",
   "last_checked": "2026-10-13T09:00:00+00:00"}
]}
```

| Field | Meaning |
|-------|---------|
| `name` | The employer's name: a label and a lookup handle (case, accents and suffixes such as `A/S` or `ApS` are ignored), not a unique key; the feed is |
| `feed` | `{"platform", "id"}`, or `null` unless `status` is `followed`. `platform` is one of `greenhouse`, `lever`, `workable`, `ashby`, `recruitee`, `pinpoint`, `smartrecruiters`, `signatur`, `recman`, `beetween`, `flatchr`, `jobtrain`, `networx`, `dayforce`, `reachmee`, `emply`, `varbi`, `visma_recruit`, `digitalrecruiters`, `taleez`, `talentsoft`, `oracle_hcm`, `eploy`, `teamtailor`, `jobylon`, `personio`, `successfactors`, `hr_manager`, `career_sites`; `id` is what that feed's scraper reads: a board token, a slug, a customer alias, a career host or URL ([entry forms](#company-entries)) |
| `status` | `followed` (read on every `collect`), `unfollowable` (its platform's terms or robots.txt rule it out, or the link names no account), `unresolved` (no feed found), `dormant` (was followed, but no relevant job for `retire_after_days`: not read until an on-topic ad of it is seen again, or `companies add`; it keeps its feed) |
| `reason` | Why it is not followed (the detection's evidence for `unfollowable`) |
| `refusal` | For an `unfollowable` employer: `must_not` (its platform's terms or robots.txt rule it out) or `cant_yet` (no way in yet, e.g. a Phenom front end with nothing readable behind it); absent otherwise |
| `found_via` | `manual` (you named it), `ai`, or the name of the board (`jobindex`, `thehub`, `hellowork`, ...) or discovery source (`linkedin`, `profession`, ...) whose results queued it |
| `evidence` | How the feed was found |
| `first_seen`, `last_checked` | ISO timestamps |
| `collect_problem` | `{"at", "outcome", "reason"}` when the last `collect` could not read the employer's feed (`outcome` `blocked` for a refusal such as bot protection, `failed` for an error), else `null`; `collect` sets and clears it, `companies list` and `why` and the app's Employers screen show it |
| `last_relevant` | ISO timestamp of the last on-topic posting `collect` wrote for the employer, or a posting of it that scored at or above `min_score`; `null` until then. A followed employer is retired when `retire_after_days` pass since the later of `first_seen` and `last_relevant` |

A malformed file is reported with its path and the entry at fault by every command (`doctor` checks it
too). Writes are atomic.

### Refused config keys

The followed employers are not listed in `config.json`: the per-platform keys
(`greenhouse_boards`, `lever_companies`, `teamtailor_companies`, `workable_companies`,
`hr_manager_aliases`, `ashby_companies`, `recruitee_companies`, `pinpoint_companies`,
`career_sites`, `successfactors_companies`) and `sites` are not part of the schema, so a config that
sets one is refused (like any unknown key; `init --set greenhouse_boards=...` too). The employers
are in `companies.json`, and `collect` reads every followed one.

## Validation

Every command validates `profile/config.json` against the `Profile` schema
(`src/door/core/profile_loader.py`) before doing anything else. Unknown keys are rejected, so
a typo such as `min_sore` is reported with its name, one line per problem, and the command
exits 1:

```
Error: profile/config.json: greenhouse_board — Extra inputs are not permitted
Error: profile/config.json: min_score — min_score must be between 0.0 and 1.0
```

`./door doctor` lists every such error without running anything else, and also
checks that the `cv_template` and `cover_letter_template` files exist (no `cv_content` file is "no CV yet", not an error).

## How a CV is written in each country

`src/door/i18n/country/<cc>.toml` has a `[cv]` block: `photo` (`"no"`, `"optional"` or `"expected"`),
`date_of_birth`, `max_pages` and `date_format` (see [adding a country](adding-a-site.md)). `prepare` hands the
tailor the block of the job's country (the country its location names, else your own `location`'s; a country
with no file gets no photo, no date of birth and two pages), and the tailor follows it on top of the ad's
language rules: no photo where it is `"no"`, one only if your profile has a `photo` where it is `"optional"`, and
`<<photo>>` where it is `"expected"` (nothing is printed when you have none). A date of birth is never added: it is
kept only if your `cv.md` already has one. A place of birth, marital status and nationality are never added, in
any country. A template that does not define `\cvphotobox` (a copy made before photos) prints no photo.

## Keys

The everyday keys below can also be set from the desktop app's Profile screen ([manual](manual-app.md#profile)); the ones for tuning a run, the advanced keys and the template paths stay in this file.

The keys you set up — `init` and `/onboard` ask for the ones without a default:

| Key | Type | Default when omitted | Used by |
|-----|------|----------------------|---------|
| `name`, `email` | string | required | tailoring |
| `location` | string | required | scrapers (search location), pre-filter, prescreen |
| `cv_template`, `cover_letter_template` | path | required, must exist | tailoring |
| `cv_content` | path | required (the file may not exist yet) | `match`, prescreen, tailoring |
| `photo` | path or `null` | none | your CV photo, a JPEG or PNG; `compile` puts it in the CV where the job country's conventions allow one (below). Set it by giving the picture to `init`, the desktop app's Profile screen or `/onboard`, not by hand: they check it, drop its EXIF and GPS data, scale it to CV size and keep it as `profile/photo.jpg`. A file `config.json` names that is missing, over 10 MB or not a JPEG or PNG is refused with the reason under the key |
| `role_targets` | list of strings, ≥1 | required | scrapers, prescreen, `match` |
| `search_keywords` | list of strings | `[]` (falls back to `role_targets`) | scrapers; `init`'s reading step (or "expand my search keywords") fills it in, in English and each of your `languages` (a Hungarian reader gets "accountant" and "könyvelő"); one list, any mix of languages |
| `topic_terms` | list of strings | `[]` (any content word of the keywords) | what makes a job title *on topic* (which employers are queued and followed, which feed postings are kept): one of these or a whole keyword. Proposed with the keywords, in each of your `languages`: your field, its subjects and neighbours (for an accountant "accounting", "audit", "tax"), never a bare role noun like "analyst". Plain words are enough: a term of six letters or more also matches as the end of a word ("physics" in "Astrophysics"), inside a word when `languages` has a compounding one (Danish, Hungarian, Swedish: "sygeplejerske" in "Intensivsygeplejerske"), and with the plural endings of your `languages` ("reward" in "Rewards"). Write `x*` (starts a word), `*x` (ends one) or `*x*` (inside one) to say it yourself. "&" reads as "and" (`m&e` matches "M&amp;E Officer"), and an all-caps term of three letters or more (`MEAL`) is case-sensitive, so it is not a "meal" |
| `remote` | `"yes"` / `"no"` / `"hybrid"` | required | pre-filter |
| `exclude` (`companies`, `keywords`) | list of strings | `[]` | pre-filter, `match` |
| `min_score` | float 0–1 | `0.65` | `match`, `jobs`, `jobs summary`, `jobs prepare` (without a job), `find` |
| `languages` | list of supported languages, by name or code: `English`, `Danish`, `French`, `Hungarian`, `Swedish` | `[]` (English) | `scrape` keeps only job ads written in these; `match` scores a job that requires another language much lower |
| `needs_work_permit` | bool | `false` | `match`: you need the employer to sponsor a visa or work permit. An ad that says it will not sponsor, or that requires an existing permit or right to work, scores 0 with the reason `work permit: ...`, so it never clears `min_score`. `false` only shows what the ad says (`jobs show`, `jobs`). Set it with `init --set needs_work_permit=true`; it applies to postings scored after the change |
| `enrich_sources` | list of strings | `[]` | `enrich` / `/expand` (the pages read when none are passed) |
| `max_age_days` | int ≥ 1, or `null` for no cutoff | `30` | `jobs`, `jobs prepare` (without a job): hide postings older than this (by `posted_at`, else `scraped_at`); `search`: the furthest back a board is read (an employer's feed has no such limit: what is new is what *The other door* has not seen); `match`, `find`: how far back to look for unscored postings |
| `retire_after_days` | int ≥ 0 | `90` | `collect`: a followed employer that yielded no on-topic posting (title with a content word of `search_keywords`, else `role_targets`) and none scored at or above `min_score` for this many days becomes `dormant` in `companies.json` and is no longer read. `0` never retires. An employer added by hand (`found_via` `manual`) is never retired; a dormant one is followed again when `search` or `discover` sees an on-topic ad of it, or by `companies add NAME` |
| `follow_ai_fallback` | bool | `true` | `follow`: for an employer every check left unresolved, ask Claude Haiku once (web search, on your Claude plan, never an API key) where its careers page is; the URL goes through the same checks and only a confirmed feed is followed (`found_via` `ai`, the URL in the evidence). Not asked again for 90 days. `false` never asks |

### Advanced keys

Tuning knobs with sensible defaults; most profiles never set them.

| Key | Type | Default when omitted | Used by |
|-----|------|----------------------|---------|
| `recheck_after_days` | int ≥ 0 | — (never re-check) | `search`, `collect` (history) |
| `linkedin_discovery` | bool | `false` | `discover`: asks LinkedIn which employers hire for your keywords and queues each new one, for `follow` to find its own job feed. LinkedIn's terms forbid automated access (as profession.hu's, HelloWork's and Jobbsafari's do), so each of these keys is your call: personal use only, at your own risk ([legal disclaimer](../LEGAL_DISCLAIMER.md)); each is off until you turn it on: `init`, `/onboard` and the app's onboarding ask about every source serving your city (yes suggested), and the app names a source never chosen at the sidebar's foot. Turning one on shows its disclaimer (what its terms say, the terms link, your decision and your risk; `init`, `init --set`, the `init_profile` tool, the app's onboarding and Profile all show the same text), and `doctor` and the run summary list the ones that are on. Skipped when there are no keywords and for a day after LinkedIn refuses. `false` turns it off. Plain HTTP, no browser needed. Every discovery source has one `<source>_discovery` key like this (default `false`), and a source that serves only some countries runs only for them; `linkedin_discovery`, `profession_discovery`, `hellowork_discovery` and `jobbsafari_discovery` are the four today. See [Discovery sources](job-sites.md#discovery-sources). |
| `profession_discovery` | bool | `false` | `discover`, Hungary only (a profile whose `location` is in Hungary): asks profession.hu which employers hire for your keywords and queues each new one with its ad link, for `follow` to find its own job feed. No ad is stored or scored. At most 30 requests a run, 3 to 6 s apart, 3 pages of 20 ads a keyword; skipped without keywords and for a day after profession.hu refuses. `false` turns it off. Plain HTTP, logged out. |
| `hellowork_discovery` | bool | `false` | `discover`, France only (a profile whose `location` is in France): asks HelloWork which employers hire for your keywords and queues each new one with its ad link, for `follow` to find its own job feed. HelloWork's terms forbid automated access, so it is your call: personal use only, at your own risk ([legal disclaimer](../LEGAL_DISCLAIMER.md)). No ad is stored or scored. At most 30 requests a run, 3 to 6 s apart, 3 pages of 30 ads a keyword; skipped without keywords and for a day after HelloWork refuses. `false` turns it off. Plain HTTP, logged out. |
| `jobbsafari_discovery` | bool | `false` | `discover`, Sweden only (a profile whose `location` is in Sweden): asks Jobbsafari which employers hire for your keywords and queues each new one with the link to its own application page, for `follow` to find its own job feed. No ad is stored or scored. At most 30 requests a run, 3 to 6 s apart, 3 pages of 30 ads a keyword; skipped without keywords and for a day after Jobbsafari refuses. `false` turns it off. Plain HTTP, logged out. |
| `scrape_workers` | int ≥ 1 | `8` | `search` and `collect`: how many sites are read at once, and how many hosts of a per-company feed (`career_sites`, `successfactors`, `teamtailor`, `recruitee`) are fetched at once; `follow` checks that many employers on different hosts at once. Pacing is per host, so each host still sees one request at a time with the usual pause; only different hosts overlap. `1` makes one request after the other |
| `verify_liveness` | bool | `false` | `find`'s liveness check (below) |
| `liveness_expiry_phrases` | list of strings | `[]` | liveness check, added to the built-in phrases |
| `dedup_source_priority` | list of site names | `[]` | cross-site dedup: which copy of a duplicate to keep. Without it, the employer's own copy (a followed feed) wins over a board's |
| `dedup_similarity_threshold` | float 0–1 | `1.0` | cross-site dedup |
| `max_postings_per_site` | int ≥ 1 | unbounded | `find`'s scrape stage (below) |
| `max_pages_per_keyword` | int ≥ 1 | `3` | `jobindex`, `workable` |
| `condense_max_chars` | int ≥ 1 | `3000` | description condense pass |
| `prescreen_top_n` | int ≥ 1 | `40` | offline prescreen (below) |
| `prescreen_min` | float 0–1 | `0.15` | offline prescreen (below) |
| `translate_titles` | bool | `true` | `scrape`'s language pass (below) |
| `translate_model` | string | `"haiku"` | `scrape`'s language pass |
| `revise_model` | string | `"sonnet"` | `revise` |
| `claude_config_dir` | path | — (the environment's `CLAUDE_CONFIG_DIR`, else `~/.claude`) | every `claude -p` call (`match`, `scrape`'s title translation, `prepare`, `revise`, `setup`'s scraper fix) and `doctor`'s login check |

More detail on a few of them:

- `verify_liveness`: when `true`, each newly scraped posting gets a lightweight HTTP GET before matching. Postings that return 404/410 or contain known expiry phrases (e.g. "position has been filled") are marked `expired` and left out of matching, which saves tokens on dead listings. 403, 5xx and network errors count as `indeterminate` and are kept.
- <a id="company-entries"></a>Company entries (a feed's `id` in `companies.json`): each feed takes what you can copy from the company's careers page.
  `greenhouse`: the token or the board URL (`trustpilot`,
  `https://job-boards.greenhouse.io/trustpilot`, its `.eu.` twin, an embed link with
  `?for=<token>`). `lever`: the slug or the board URL; a slug the US host doesn't
  know is tried on Lever's EU host, and a `jobs.eu.lever.co/<slug>` URL goes straight there.
  `workable`: the account slug or `apply.workable.com/<account>/`.
  `ashby`: the board name or `jobs.ashbyhq.com/<board>`. `recruitee`:
  the subdomain slug (`famly`) or the company's own careers host when it points at Recruitee.
  `pinpoint`: the subdomain slug (`factbird` for `factbird.pinpointhq.com`).
  `oracle_hcm`: `<host>/<site>` (`ejqi.fa.ocs.oraclecloud.eu/CX_1001`) or any candidate-experience link into the site.
  `emply`: the tenant slug (`dca` for `dca.career.emply.com`) or any link on its career host.
  `varbi`: the tenant slug (`ki` for `ki.varbi.com`) or any link on its host.
  `eploy`: the careers site's host (`vitalityweb.eploy.net`, or the employer's own domain such as `portal.careers.turing.ac.uk`) or any link on it; the list is the site's public RSS data feed (`/feeds/datafeed.ashx`), each ad its whole text.
  `visma_recruit`: the customer's list id, the `guidExtSoftware` of the `recruit.visma.com/External/OJCustomer3/AssignmentList.aspx?guidExtSoftware=<id>` link its own website carries (`f636d73d-8356-43c6-99bd-ba01addf1b55` for Nässjö kommun), or that link, or one of its ads' `AssignmentView.aspx` links. An employer that lists its ads on its own website (and sends only the apply link to Visma) is followed by that list page's address (`https://www.regionvasterbotten.se/sok-jobb`). An apply link (`/spa/public/apply?guidAssignment=`) names only the ad.
  `personio`: the account slug (`pno-group-europe` for `pno-group-europe.jobs.personio.com`), the whole host for a `.personio.de` page, or any link on it; its public XML feed lists every ad with its text.
  `talentsoft`: the career host (`agrica-career.talent-soft.com`, or the employer's own host that serves `/offre-de-emploi/liste-offres.aspx`) or any link on it.
  `taleez`: the tenant slug (`donecle` for `donecle.taleez.com`), any link on its career host or the spontaneous-application link `taleez.com/apply/sp/<slug>`; a job's own link (`taleez.com/apply/<job>`) names no tenant. The list is the tenant's `/api/careez`, each ad its JSON-LD.
  `digitalrecruiters`: the career site's host (`recrutement.monoprix.fr`; the platform has no shared host, each employer's site is on its own domain, found by the page's `api.digitalrecruiters.com` config) or any link on it. The list is the site's `sitemap.xml`, each ad its JSON-LD.
  `dayforce`: `<client>/<portal>` (`natus/CANDIDATEPORTALSENSORY`) or any `jobs.dayforcehcm.com` link into the portal.
  `reachmee`: `<installation>/<customer>/<site>` (`I003/354/5`), or any `web103.reachmee.com/ext/…?site=` apply link or `customerjs` embed that names the publishing site.
  `signatur`: the customer's ClientId (`1449`), or any `portal.signatur.dk` link carrying `ClientId=`.
  `recman`: the tenant slug (`pn` for `pn.recman.page`), a `<tenant>.recman.io` host or the employer's own career host that points at Recman (`stillinger.signo.no`); a job board's apply link (`apply.recman.page/job_post.php?…`) is followed to that host. The list is the site's `sitemap.xml`, each ad its JSON-LD.
  `flatchr`: the career-site slug (`flatchr` for `careers.flatchr.io/fr/company/flatchr`), a `<slug>.flatchr.io` host or any link into the career site; its `company/<slug>.json` list holds every open ad in full.
  `jobtrain`: the tenant (`leighacademiestrust` for `www.jobtrain.co.uk/leighacademiestrust/`, the employer is the first path segment, never the shared host) or, for a tenant on a host of its own, that career host (`jobs.crisis.org.uk`, a CNAME for `jobs-crisis.jobtrain.co.uk`, found by the CNAME or by the page's `SITE_BASE_PATH` script variable). The list is the jobs page's `Home/_JobCard` cards, each ad its JSON-LD.
  `networx`: the client id (`3509`), the `cid` of the employer's adverts on `networxrecruitment.com` (or `current-vacancies.com`), or an advert or search link that carries it; the board is shared by many employers, so only that client's adverts are read (the search narrowed to it, each ad's page for its text).
  `beetween`: the tenant slug (`giboire` for `giboire.nous-recrutons.fr`) or the employer's own career host (`recrutement.clermontmetropole.eu`). The list is the site's WordPress job route (`/wp-json/wp/v2/job`), each ad its JSON-LD.
  `smartrecruiters`: the company identifier, the first path segment of its `jobs.smartrecruiters.com/<id>/…` links (`ncs3`).
  `teamtailor`: the subdomain slug (`templafy`) or the company's own career host
  when it points at Teamtailor (`careers.veo.co`); its public `jobs.json` feed is read page
  by page, with `jobs.rss` as the fallback. `jobylon`: the company number (`2420` for Lyko), found from
  an `emp.jobylon.com` ad or apply link or from a career page that embeds Jobylon's widget; its public company
  widget lists the jobs and each new ad's page gives the text. `successfactors`: the careers host
  (`careers.novonordisk.com`). `hr_manager`: the customer's alias in its HR-Manager
  feed or job-agent link (`customer=`): `regionh`, `kkdk`, `statensrekrutteringsloesning_tr`.
  The state's recruitment service files university ads under each university's own alias,
  so list those separately.
- `prescreen_top_n`: after pre-filter and dedup, `scrape` ranks the remaining postings offline, with no LLM call (title similarity to `role_targets`, skill overlap with the CV, seniority match, location compatibility). Every on-topic posting (its title, or its English translation, on `topic_terms` or the keywords) at or above `prescreen_min` is left unscored for the matcher; `prescreen_top_n` caps the off-topic ones, with the on-topic ones counted against it. The rest are written back with `score=0.0` and a `"prescreen: ..."` reason, so they stay on disk (counted as filtered out by `jobs summary`) instead of being deleted.
- `exclude.keywords`: each keyword matches a whole word in the title, in any case (not the description, which may mention the students or interns a lead role manages; scoring still sees the keywords and the whole ad), so `"intern"` drops "Data Intern" but not "international team". End a keyword with `*` to match the start of a word (`"internsh*"`). A keyword that is an ordinary, unrelated word in the ad's language is not applied to that ad: Danish *intern* means "internal", so `"intern"` doesn't drop a Danish ad about "intern kommunikation" (the list per language is `false_friends` in `src/door/i18n/lang/<code>.toml`).
- `location`: the pre-filter also accepts the city's other names from `src/door/i18n/country/<code>.toml`, so `"Copenhagen"` keeps postings in "København S", "Kastrup" or "Frederiksberg", and a location with a remote, home-based or work-from-home word in any supported language ("hjemmearbejde", "home-based", "hjemmebaseret") is always kept. Which postings are foreign (`location_is_non_local`) is decided from the places `foreign_places` in `src/door/i18n/common.toml` lists: every country of the world (English names, plus Danish and Hungarian ones) and the larger cities, and the words "abroad", "overseas", "udlandet", "külföld"; a bare city that is on no list (and has no country beside it) is ambiguous and kept.
- `remote`: with `"yes"` or `"hybrid"` the pre-filter keeps every location. With `"no"` it keeps what is commutable: the city (and its names), its commute area (the towns within about an hour's commute in the country file's `[commute]`, e.g. Hillerød, Roskilde and Køge for Copenhagen) and any location that names no known place (a workplace such as "Rigshospitalet" is ambiguous, like an empty location, and the matcher judges it). It drops only a location that names a known place outside them (Aarhus, Berlin).
- `languages`: the languages of the job ads you want, not your language skills: those (with levels, e.g. "Danish — conversational") belong in your CV, which the matcher reads. With `["English"]`, `scrape` drops every ad written in Danish or any other language; with `["English", "Danish"]` it keeps both. Dropped ads get `score=0.0` and a `"language: ..."` reason and stay on disk (counted as filtered out by `status`); an ad whose language can't be detected from its description (too little text) is dropped as well. An ad with no description at all is always dropped (`"no description"`): there is nothing to score or tailor it against. The supported languages are English, Danish, French, Hungarian, Swedish: the offline filters need each language's words, so a language is supported when it has a file in `src/door/i18n/lang/`; an unsupported entry, or a level such as `"Danish (B1)"`, is rejected when the config is loaded.
- `translate_titles`: `scrape` tags every posting with the language it is written in (`language`) and gives each kept title not in English (with `languages` including Danish) an English `title_en`, which prescreen compares with `role_targets` alongside the original title, and `list`/`show` print next to it. The titles go to `claude -p` in batches of 50 (one or two calls per scrape, from your plan's quota); the matcher and the tailor still read the original ad. If the call fails, or `claude` isn't installed, the original title is used and `scrape` says so. Set it to `false` to make no call at all.
- `claude_config_dir`: the `claude` config directory whose login pays for *The other door*'s `claude -p` calls, e.g. `"~/.claude-personal"` when you keep a personal plan beside a work one. A shell alias like `alias claude-personal='CLAUDE_CONFIG_DIR=~/.claude-personal claude'` only exists in your interactive shell, not for the programs *The other door* starts, so set the directory here: *The other door* passes it as `CLAUDE_CONFIG_DIR` to every `claude` it runs, overriding the environment's, so a conversation, a terminal and cron all use the same plan. `doctor`'s `claude login` check asks that directory and names it. When several people run `./door serve` on one machine, each profile needs its own: `serve` refuses a second instance on a plan another person's already uses.
- `prescreen_min`: a posting, on topic or not, must reach this offline prescreen score to be kept, even if there's room left.
- `max_postings_per_site`: stop each site after this many *new* postings have been written. This keeps runtime predictable: an unbounded Jobindex run currently collects ~260 search hits and fetches a detail page for each at ~2s apiece, roughly 10 minutes for one site.

Jobindex (the slowest scraper — see `max_postings_per_site` above) writes each posting to disk as soon as it's fetched rather than only once the whole site finishes, and skips the detail-page fetch entirely for postings already recorded in `jobs/history.json` within the `recheck_after_days` window — both make an interrupted or repeated `scrape` run cheap: postings already written survive a Ctrl-C or crash, and already-seen postings cost zero extra requests on the next run.

Every scraped posting also gets a `description_condensed` field — a deterministic, boilerplate-stripped version of `description` (drops "about us"/benefits/EEO/how-to-apply sections, keeps role summary, requirements, responsibilities, salary and language-requirement lines) used for prescreening and, eventually, LLM matching. `description` itself is never touched, so `jobs show <job_id>` always has the full original text (on a terminal, `d` opens it in the pager).

The entire `profile/` directory is gitignored — your CV and config will never be committed.
