# Contributing to The other door

**A personal project.** *The other door* is built by one person in their spare time, for their own job
search and a few friends'. Issues and pull requests are welcome, but no support, reply or release date
is promised. A security problem goes through [SECURITY.md](SECURITY.md), not an issue.

This file is for working **on** door. For using it, see [README.md](README.md). The
conventions and rules an implementing agent follows (TDD, offline tests, plans only, one
core per command) are in [CLAUDE.md](CLAUDE.md); the design is in
[docs/architecture.md](docs/architecture.md): start with its
[engine overview](docs/architecture.md#the-engine) (the flow, the life of an employer, and why).

## Setup

```bash
./scripts/setup.sh            # Poetry, dependencies, prerequisites (asks first)
poetry install                # the dev group (pytest, responses, genbadge) comes with it
./scripts/run-test.sh         # offline suite + coverage + badge
./scripts/run-test.sh --live  # opt-in smoke tests against the real sites
```

## Rules of thumb

- **Test first.** A failing test pins the behaviour, then the minimum code makes it pass.
  Tests are offline by default; anything touching the network or the `claude` CLI is
  marked `live`.
- **One core, two adapters.** A new command is a module `src/door/commands/<name>.py` with a
  `_<name>_core` function that returns a dict and never prints and a Click command that
  renders it (registered in `src/door/cli.py`), and an MCP tool in `src/door/mcp_server.py` mapped in `CLI_COMMAND_TOOLS` —
  `tests/commands/test_mcp_server.py` fails until the two lists match.
- **Call through the module.** Use `scrape_cmd._scrape_core(...)` and `workspace.JOBS_DIR`,
  not names imported into your module, so a test that patches the defining module reaches
  every caller (see `CLAUDE.md` → Code layout rules).
- **Plans only.** Every model call goes through `claude -p`; there is no API key anywhere.
- **Skills and agents call tools**, never `./door` (`tests/claude/test_claude_files_guard_unit.py`).
- **Docs follow the code.** `tests/docs/test_docs_unit.py` fails when a skill, site or config
  key exists that `docs/` doesn't name, or a doc names a skill that doesn't exist.
- The offline suite runs on every pull request (`.github/workflows/tests.yml`); say in the
  PR that `./scripts/run-test.sh` passed locally too, since that also refreshes the badge.
- **A new source follows the source rule below**, and its PR says which terms were read
  and what robots.txt says.

## Which sources may be added

The bar is the site's terms: a new source may use any tool
*The other door* has (HTTP, sitemaps and markup, an undocumented feed) as long
as its terms don't forbid it. Terms that are silent or ambiguous on automated access
are fine; terms that expressly forbid scraping, bots or text-and-data mining are not (that
is why Workday's search API is out; LinkedIn is used only to find employers, see [docs/job-sites.md](docs/job-sites.md#discovery-sources)). Read the site's
terms before writing code and record one verdict for it (`allowed`, `unsure` or `reserved`, with
`Site(terms_url=..., verdict=..., terms_summary=...)`; see [How *The other door* fetches](docs/job-sites.md#how-the-other-door-fetches)):
a site whose terms forbid automated access can only be an opt-in discovery source, and one whose
terms reserve its content is never fetched. A source must not need each user to
sign up for an account or API key, and every request is **logged-out**. Requests go through
`PoliteSession`, which paces each host (0.2 to 0.5 s for employer feeds) and reads
**robots.txt** for sitemaps and `Crawl-delay`; the guard tests fail on **CAPTCHA** solving, proxy rotation or a spoofed fingerprint. Postings keep their
source URL, so *The other door* always **link back** to the ad it read. In the pull request, say which
terms you read and what robots.txt says (the scraper's module docstring gets the same,
and its row in [docs/job-sites.md](docs/job-sites.md#all-sites) the date you checked).

## Developer skills

Claude Code skills prefixed `dev-` drive the issue workflow: `/dev-resolve <issue>` runs
research → plan → TDD implementation → validation, `/dev-pr` opens and watches a pull
request, and `/dev-add-scraper <site>` scaffolds a new scraper. Each step also exists on
its own (`/dev-research`, `/dev-plan`, `/dev-implement`, `/dev-validate`); see
[docs/skills.md](docs/skills.md#developer-skills) for what each one does.

## Adding a scraper

The step-by-step guide, including adding a new country, is
[docs/adding-a-site.md](docs/adding-a-site.md); `/dev-add-scraper <site> [country]`
scaffolds it. A scraper is a
stateless `scrape(config, known_ids=..., since=...)` returning serialised `JobPosting` dicts; `since` is the freshness cutoff (a `datetime` or
`None`) it may use to filter at the source. Parsing helpers stay pure so they can be tested
from saved payloads without the network.

A site module imports `door` code only from `door.scrapers.sdk` (guard: `tests/scrapers/test_scraper_imports_unit.py`; see [adding a site](docs/adding-a-site.md)).

Every scraper also exposes `probe(config) -> ProbeResult | None` (`ProbeResult` is in
`src/door/scrapers/__init__.py`), the check behind `doctor`'s `scraper: <site>` line. A probe
fetches page 1 only (the first search keyword, or the first configured board/account/host),
maps the results to `JobPosting` dicts without detail fetches, and returns `{raw, ext,
postings, structure_ok}` plus an optional `reason`, `wall` (login/bot challenge) and
`unreachable`. It must have no side effects: never `record_error`, never write, never take
a lock. Return `None` when there is nothing to probe (no board configured). `structure_ok` is False only for a page that arrived but lost the structure the
scraper parses; walls and network errors are `wall`/`unreachable`, which `doctor` reports as
a warning rather than drift. `tests/scrapers/test_scrapers_probe_contract_unit.py` fails for a
scraper without `probe()`, and each scraper's fixture test needs an ok and a drift case.
`run_probe` and `probe_failure` in `src/door/scrapers/__init__.py` do the fetch/parse
bookkeeping. On drift, `doctor` saves the raw response to `jobs/drift/<site>/`, and `setup`
can hand it to the scraper-fixer agent (`.claude/agents/scraper-fixer.md`).
