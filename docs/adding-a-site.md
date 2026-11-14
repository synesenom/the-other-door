# Adding a site or a country

*The other door*'s own job boards cover Denmark; everywhere else it relies on the sites that work
in any country (see [Supported countries](job-sites.md#supported-countries)). Adding the
top boards for your country is the most useful contribution you can make, and it is
self-contained: one module per board, one line per board in a registry, and (for a new
country) its data files.

## Where the code goes

```
src/door/scrapers/
├── __init__.py, browser.py, http_client.py   # shared helpers
└── <site>.py                                 # one module per board: jobindex.py, thehub.py, greenhouse.py, …
```

Which countries a board serves is not a folder but a field of its registry entry (step 3):
the ISO 3166 codes of the countries it covers, or none for a board that works in any
country (a global board searched by `location`, or an applicant-tracking system each
company hosts).

## Steps

1. **New country only:** add its data files first (step 4), since a site can only be
   registered for a country that has `src/door/i18n/country/<cc>.toml`. Add the country's rows to
   `COUNTRIES` in `tests/pipeline/test_pipeline_countries_end_to_end.py` too (an offline `find` per
   country and ad languages).

2. **Write the scraper** at `src/door/scrapers/<pkg><site>.py`, test-first, where `<pkg>` is the
   folder of its kind: `boards/` for a board searched by keyword, `discovery/` for a source read only
   for its employers (a discovery source), and `feeds/` for an employer feed platform (`Site.module`
   works it out from the registry entry). It is one
   stateless function:

   ```python
   def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
       ...  # a list of JobPosting dicts
   ```

   Also add a side-effect-free `probe(config)` that fetches page 1 only; it is what
   `doctor` uses to notice when the site changes (contract in
   [CONTRIBUTING.md](../CONTRIBUTING.md#adding-a-scraper);
   `tests/scrapers/test_scrapers_probe_contract_unit.py` enforces it).

   Read the search terms from `config["search_keywords"]` (falling back to
   `role_targets`) and `config["location"]`; `kwargs["since"]` is how far back to look.
   Report progress with `report` from the SDK (`report("'accountant': 12 results")`,
   or `report("detail", i, total)` in a loop) and never `print`: on the MCP server stdout is the
   protocol stream, and `find` shows the events live. When a problem needs the user's attention (a
   blocked request, a page that no longer parses), call `record_error()` too, since events are ephemeral. No
   `__main__` demo block either: `./door find search --boards <site>` runs a board (and `./door find match` scores what it finds); a per-company feed is read by `./door find collect` once you follow an employer on it.
   **Import only from `door.scrapers.sdk`.** A site module has no other `door` import
   (`tests/scrapers/test_scraper_imports_unit.py` fails on one, nested imports included): the SDK
   re-exports `JobPosting`, `make_job_id`, `PoliteSession`, the reporting and probe helpers, and wraps
   the matching and i18n helpers (`on_topic`, `city_names`, `split_urls`, ...). Its module docstring
   is the reference. If a scraper needs something it lacks, add a wrapper there. The engine puts two
   runtime keys in `config`: `_mode` (`"search"` or `"collect"`) and `_country` (the profile
   location's country as a lowercase ISO code, or `None`); read the country with
   `sdk.country(config, served)`, where `served` is a module constant `_SERVED` copied from the
   site's `countries` (`thehub.py`, or a discovery source's `COUNTRIES` as in `profession.py`; a test pins it to the registry), and the look-back
   window from `since` with `sdk.look_back_days(since, now)`.
   Keep parsing in small pure functions so it can be tested from saved pages. Use
   `PoliteSession` (`http_client.py`, via the SDK) for HTTP. Copy an existing scraper of the same kind:
   `jobindex.py` (HTML with embedded JSON), `greenhouse.py` (a public JSON API), `thehub.py`
   (a Nuxt page whose `window.__NUXT__` script is evaluated with the embedded `quickjs` engine).

   **What may be added, and the terms verdict.** Read the site's terms before writing any code and record
   one verdict for it ([How *The other door* fetches](job-sites.md#how-the-other-door-fetches)):

   - `allowed`: the terms allow reading the ads or say nothing against it. "No terms found" and
     "unclear" are `allowed` too, said in the module docstring.
   - `unsure`: the terms forbid automated access on the host *The other door* reads. Such a source is
     never a board or a feed that runs by default: it is only an employer **discovery** source (a module
     in `scrapers/discovery/`, registered in `core/discovery_sources.SOURCES` and run by `discover`: LinkedIn,
     profession.hu, HelloWork, Jobbsafari; see `scrapers/discovery/profession.py`) with its own
     `<source>_discovery` switch, off until the user turns it on, and the disclaimer shown when they do.
     A test fails for an `unsure` `Site` that has no switch. It runs under LinkedIn's constraints:
     - logged out (no login, cookies or session);
     - paced and capped (a request budget per run);
     - stops for the run on pushback and rests 24 h after a refusal;
     - keeps only employer names, titles and job links (the candidates queue), never ads or
       descriptions.
   - `reserved`: the terms expressly reserve the content against scraping or text-and-data mining: never
     fetched (or not proposed at all).

   The verdict goes in the registry entry (`verdict`, `terms_summary` in one sentence, `terms_url`; a
   discovery module has `VERDICT`, `TERMS_SUMMARY`, `TERMS_URL`), and the module docstring has a "Terms"
   passage quoting what it rests on (or saying that no terms were found). When in doubt about whether the
   terms forbid it, read them again; do not ask for robots.txt to be obeyed or for the User-Agent to
   change: both are decided. No source that
   needs credentials of any kind (an account, an API key, an OAuth client each user registers), and
   no login: an official API that wants a key is not a route, however good its data.

   **When a site can't be a board, it is a discovery source.** Terms that forbid automated access, listings
   that only a credentialed API serves, or pages *The other door* can't parse do not drop a site: if
   its logged-out pages name the employers that hire (with a job or apply link), it is read as a
   discovery source under the constraints above, and `follow` goes straight to each employer's own
   feed (its ATS platform) or career site. Only a site with nothing readable logged out (a login,
   CAPTCHA or bot wall on every page, or listings that exist only in a real browser) is skipped.

   Requests go through
   `PoliteSession`, which reads robots.txt for sitemaps and `Crawl-delay` (always honoured)
   ([How *The other door* fetches](job-sites.md#how-the-other-door-fetches)); a guard test fails
   on CAPTCHA solving, proxy rotation or a spoofed browser fingerprint.

3. **Register it** with one entry in `SITES` in `src/door/core/sites.py`:

   ```python
   Site("stepstone", label="StepStone", countries=("de",), terms_url="https://www.stepstone.de/agb",
        verdict="allowed", terms_summary="no clause on automated access"),
   # or, for a board that works in any country:
   Site("stepstone", label="StepStone", terms_url="https://www.stepstone.de/agb",
        verdict="allowed", terms_summary="no clause on automated access"),
   ```

   `label` is the site's name as people write it (the desktop app shows "via StepStone" under a
   posting). `countries` decides which sites `init` offers for a `location`; every code in it needs
   a country file (`tests/core/test_sites_unit.py` checks). A board serving several
   countries lists each one it has been tested for, and adding a country to it later is
   one code plus that country's file.

   A per-company feed names its key too (`config_key="greenhouse_boards"`: the key `_scrape_core` fills from the platform's followed employers in `profile/companies.json`; it is the one source, `sites.FEED_SITES`), so an empty scrape can say what to follow. A feed's module also says how its feed is *found*, so `companies add` and `follow` need no other edit: `detect_url(url)` (a careers link on the platform and the entry it names) and `feed_url(entry)` (the endpoint that confirms an entry by its jobs, or `None`), and where they apply `detect_cname`, `detect_html`, `name_probes(slug)` (public endpoints to try for a company name) and `FEED_KEY`; add the module's name to `ats_detect.PRECEDENCE` (the one place the dispatcher names platforms; the order is the order links to several platforms on one page are weighed in). `sdk.Detection`, `sdk.Probe`, `sdk.parts`, `sdk.first`, `sdk.NOT_ACCOUNTS` and `sdk.unfollowable` build them; An optional `resolve(session, det, url)` reads further after a detection; a platform that cannot be followed but whose link names the employer returns its detection with `employer` (the name) and `site` (its own website, if given) set, and `follow` then tries that site's platform and that name's feeds before the employer stays `unfollowable` (Visma Recruit). `tests/scrapers/test_feed_contract_unit.py` checks the shape.

   A board's module names its own hosts, `JOB_BOARD_HOSTS = ("stepstone.",)` (markers in a host; `JOB_BOARD_EXACT` for whole hosts): a link there is an ad on the board, so `follow` never takes it for an employer's career site (`tests/core/test_ats_detect_unit.py` fails for a board without one).

   That one entry makes a board searched for every profile in its countries and valid in `--boards`, makes `scrape` import it,
   and puts it in the pool `scrape` runs the sites in.

4. **New country only — its words and places.** The matching passes read everything that
   depends on language or country from data files in `src/door/i18n/`, so a new country
   is no code change there:

   - `src/door/i18n/country/<cc>.toml` (ISO 3166 code): its `languages`, the `currency`
     words a salary line uses, company-form `legal_suffixes` (`"gmbh"`; also dropped, with the country's names, from the slugs `follow` tries an employer's name as) that dedup
     strips, and `[cities]`: each city's other names (`munich = ["münchen*"]`), which
     the pre-filter uses to match the profile's `location`, and the optional `[commute]`: each city's towns within about an hour's commute (`copenhagen = ["hillerød", "roskilde"]`; every key is a city of the file), which an on-site profile (`remote = "no"`) keeps. For employer feed detection (`follow`, `companies add`):
     `tlds` (its domain endings, `["hu"]`; the first is the one `follow` tries an employer's career host under, else the ISO code),
     `career_hosts` (host labels its employers use for a career site, `["karrier", "allas"]` for `karrier.acme.hu`; also
     never read as an employer's name and tried on an employer's own domain), `subsidiary_words` (what a subsidiary's or
     branch's name ends with that is no part of its employer's own, `["svenska", "i sverige"]`: trimmed, with the country's
     names and legal forms, before `follow` looks the name up on Wikidata) and `job_boards` (whole domains, the domain or a subdomain, of its job boards and
     recruiters, never read as an employer's own site). Words around a name that no URL slug carries and global
     domain endings are in `common.toml` (`slug_suffixes`, `generic_host_labels`, `tlds`).
     The `[cv]` block says how a CV is written there, which `prepare` hands the tailor for a job in the country:
     `photo` (`"no"`, `"optional"` or `"expected"`), `date_of_birth` (whether a CV there conventionally has
     one: it only means "keep the one `cv.md` already has", the tailor never adds it), `max_pages` and
     `date_format` (the country's all-numeric full date, `DD`, `MM` and `YYYY` once each). Each value rests on a
     source read for the country (the law on photos and age, the public employment service's CV advice), cited
     in the research report; a law that forbids requiring a photo makes it `"optional"` at most. Place of birth,
     marital status and nationality are never settings: the tailor never adds them. A country with no block gets
     the neutral default (no photo, no date of birth, two pages).
   - `src/door/i18n/lang/<code>.toml` (ISO 639-1 code) for each of those languages that
     isn't there yet. Until a language has a file, profiles can't list it in
     `languages` and `scrape` drops its ads. Copy `da.toml`, which has everything a
     supported language needs: section
     `headings`, requirement / remote / salary `markers`, `seniority` words mapped to
     the canonical levels (`junior`, `senior`, `lead`, `principal`, `head`, `manager`, and `academic` for postdoc, assistant or associate professor and professor, one level so any rank matches any other), `false_friends` (English words that mean something else in
     it), `stop_words` (connecting words like "of" that a search phrase drops), letters to `transliterate`, `title_tags` (the gender tags its job titles carry, `"H/F"`, `"m/k"`: letters split by `/` or `.`; every board and feed posting's stored title drops them, bare or in parentheses, in any case), `months` (the twelve month names and abbreviations with their numbers, all or none; a date written out is read with them), and the `language_requirement` and `work_permit` (no sponsorship, permit required, sponsorship offered) phrases the matcher
     looks for ("Deutsch ist ein Muss"), and the `[careers] link` words (and phrases) that make a link a careers page ("Karriere", "Stellenangebote"; `companies add` follows them).

   Word lists match whole words in any case; end one with `*` to match the start of
   longer words (compounds). A language's headings, markers and seniority words apply only
   to ads detected in that language (and English ones to every ad), so an ordinary word in
   one language can't trip another's ads; two files that spell a letter or rank a seniority
   word differently fail on load. `tests/i18n/test_i18n_unit.py` checks every file, and an
   unknown key or seniority level fails loudly. Add a few hand-written ads in the
   language to the condense and prefilter tests. A new language also goes in the supported-language
   lists in `configuration.md`, `job-sites.md` and `how-it-works.md`; the `init` wizard, its `--languages` help, the MCP tool
   description and `/onboard` pick it up from the file.

5. **Document it:** the module docstring states the endpoint, the config key, the terms you
   read (its `terms_url`) and what robots.txt says; a row in [job-sites.md](job-sites.md)
   gives the site, its countries and the date you checked (and, for a new country, the
   Supported countries table there and the list in the README); and a row in the scrapers
   table in [architecture.md](architecture.md#scrapers-doorscrapers).

6. **Test:** tests and saved fixtures go next to the other sites':
   `tests/scrapers/<pkg>test_<site>_{unit,scrape,live}.py` and
   `tests/scrapers/<pkg>fixtures/<site>/`. The live file has one probe-sized test per mode, named
   `test_<site>_<mode>_live` and built on `tests/live_utils.py`: `listing` (page 1 through `probe`, the field
   contract on its postings), `page2` and `details` (one more page, two detail pages; a `NO_PAGE2` or `NO_DETAILS`
   constant says why the site has none), `zero_hits` for a board (with a saved real zero-hit page in
   `tests/live_matrix.py`) and `detection` for a feed platform (a real employer's careers page in
   `tests/live_employers.py`). `tests/scrapers/test_live_modes_unit.py` fails until each mode that applies has its test. A fixture keeps a real response's structure but not its content: trim
   it to what the parser reads, rewrite the remaining text (descriptions, blurbs, contact lines) as new text in the
   same language, keep titles, companies, dates, ids, URLs and anything a test asserts on, and make every person up
   (`kontakt@example.com`, `00 00 00 00`); `tests/core/test_fixture_privacy_unit.py` fails on a real address, number
   or key. `./scripts/run-test.sh` must pass. `tests/core/test_sites_unit.py` fails until the module
   and the registry agree.

In Claude Code, `/dev-add-scraper <site> <country>` builds one site this way, and
`/dev-add-country <country>` does a whole country: it researches the boards and their terms,
asks which to build, writes the data files and the scrapers test-first, documents them, runs
the live smoke tests and tries the country with two fake profiles, one reading only English and one
English plus the local language (`scripts/sandbox.py <dir> <command>`
runs the real CLI against a throwaway `profile/` and `jobs/`).
`/dev-add-profession <titles> <country>` does the same for one profession, given as its job titles, in a country
that already has its data file. It finds where that profession's jobs are posted: boards,
profession and union job banks, the ATS platforms its employers use, and discovery sources.
It builds the ones you pick, with live smoke tests that search for the profession, and checks
the result with a fake profile of the profession. See
[CONTRIBUTING.md](../CONTRIBUTING.md) for the general rules (test-first, offline tests,
no API keys).

`scripts/country_smoke.py <cc> [--langs en|local|both] [--profession NAME] [--stub-scoring] [--collect N] [--budget N]`
repeats that country run on demand: it searches every board serving the country, runs `discover`
with a small LinkedIn budget, a `follow` dry run and a real one, `collect` on a few followed
employers and `match`, all in throwaway sandboxes under `thoughts/country/<cc>/`, and writes
`smoke-<date>.md` with one PASS / FAIL / SITE-SIDE / SKIP line per step and board. The exit code is
1 only when a line FAILs; a resting board or a refused LinkedIn is SITE-SIDE. Run it before a release,
after a board breaks, or after a change to locality, language or follow; it hits real sites and is
not in CI. A new sandbox inherits the previous one's rest state, so a repeat run respects the 24 h
rests. A country needs its rows in the script's `PROFILES`. `--profession nurse` runs one Danish
profession's row alone (the six profiles of `tests/professions.py`, #427) instead of the mixed one.
