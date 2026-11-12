# Your data

Your files stay on your computer, inside this checkout, unless you connect Google Drive
(see below). Both folders below are gitignored, so nothing personal is ever committed.

Two things do leave your computer:

- **To Anthropic, through your own Claude plan:** each posting with your CV when it is scored, and
  your CV, story bank and the posting when an application is prepared or revised. The `claude`
  command line tool sends them, under your Claude account and Anthropic's terms.
- **To your Google Drive, if you connect it:** one archive of `profile/` and `jobs/` (see below).
  How *The other door* uses your Drive is on its [privacy page](https://enysmones.com/the-other-door/#privacy).

| Folder | What's in it |
|--------|--------------|
| `profile/` | your config, the employers you follow (`companies.json`; each entry's other names are its `aliases`, formerly `also`, migrated when read), CV, LaTeX templates and story bank |
| `jobs/` | scraped and scored postings (`postings/<date>/<site>/`; day folders an older version left directly under `jobs/` are moved there the next time *The other door* reads or writes them), the history and application ledgers, run records (a block per `find` step), the candidates queue (`candidates.json`: employers `follow` has yet to look at), the discovery state, one file per source (`discovery/linkedin.json`, `discovery/profession.json`; an older `linkedin_discovery.json` is copied there the first time and kept), the `market` reports (`market/report-<date>.md`) the salary estimates (`salary.json`: `{job_id: {low, high, currency, period, position, sources, as_of}}`, from `jobs salary` or `jobs prepare`; delete an entry to ask again) and its skill-name groups (`skill_aliases.json`: `{"variant": "Canonical"}`, `null` for a name that is not a skill; edit it freely, your edits are kept), and the generated CVs and cover letters (`jobs/output/<job_id>/`); every posting carries an `integrity` verdict (see [how it works](how-it-works.md#the-ad-is-untrusted-input)) |

By default both folders sit in the checkout. Set the environment variable `DOOR_HOME` to a
folder and *The other door* keeps `profile/`, `jobs/`, `backups/`, `upskill/`, `logs/` and a generated `.mcp.json`
there instead (see [configuration](configuration.md#where-your-data-lives)); `./door doctor`
prints the folder in use.

To keep your progress, back these two folders up. Deleting the checkout or running
`git clean -fdx` deletes them too.

## The problem log

`logs/door.log` in the data folder keeps one line per thing that went wrong, with the time:
a tool call that failed or answered an error (its name and the message, never what it was
given), a crash, a warning a tool returned, and from each `find` the sites that failed or came
back empty and the ads left unscored (by id). The desktop app adds what its window was refused
and a server that stopped (with the end of its error output). It holds no CV text, profile
values or ad text. At about 1 MB it moves to `door.log.1` (and `door.log.2`); older lines go.

`./door data report` (or Settings → Report a problem → Save logs… in the app) packs it with
the last five run records (counts, outcomes and errors only), `doctor`'s checks, and the version
and OS into one `door-report-<date>.zip` to send to whoever helps you. Emails, the data folder and
your home folder are masked in it, and nothing from `profile/`, no postings and no ledger go in.

When something keeps going wrong, the app says so with one line at the foot of its sidebar,
"Something keeps going wrong. Send a report" (`status_summary`'s `recurring_problem`,
`src/door/core/recurring.py`): the same job site failed in each of the last 3 runs that tried it,
ads were left unscored in each of the last 2 runs, the server stopped or would not start in the last
7 days, or the same tool failed 3 times within 24 hours. Saving a report writes its time to
`logs/reported_at`, and only what happened after it counts; the line also goes once the failure stops
(the site's next run works). A failure that happens once is said nowhere: the next run retries it.

## Moving to another computer

```bash
./door data export       # writes door-export-<date>.tar.gz here
# copy the file over, set up The other door there (./scripts/setup.sh), then:
./door data import door-export-2026-10-09.tar.gz
```

Or say "export my data" / "import this export" in a conversation.

- **`data import` replaces, it doesn't merge.** Whatever `profile/` and `jobs/` the new
  computer had are moved to `backups/<timestamp>/` first, so nothing is lost.
- **Check paths afterwards.** `data import` warns when a path in `profile/config.json` (such
  as `cv_template`) doesn't exist on the new computer. `claude_config_dir` is the exception: it
  names a Claude plan folder of one computer, so it is left out of the archive and an import keeps
  the one this computer already has.

## Older data

Job ids used to be `<site>.<company>.<title>`; they are now `<site>.<platform_id>`
(`jobindex.h1708816`), and `jobs/history.json` is keyed by the same id. Data from before that
(an old `data export` archive, say) is converted with
`poetry run python scripts/migrate_job_ids.py --dry-run` to see the counts, then without
`--dry-run`. It backs the originals up to `backups/<timestamp>/jobs` first, and running it again
changes nothing.
