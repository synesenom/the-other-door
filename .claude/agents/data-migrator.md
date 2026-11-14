---
name: data-migrator
description: Write the upgrade step (or, on a major version bump, empty the step lists) a release needs for the data the previous release wrote — diff everything `src/door/core/stored.py` names between the last tag and main, tell a rename from a removal from a new optional field by reading the PRs, and write at most one step per folder test-first, or report "no step needed" item by item. Spawned by the /dev-release skill before tagging; not for direct use. The prompt must include the previous tag and the merged PRs.
model: opus
tools:
  - Bash
  - Glob
  - Grep
  - Read
  - Edit
  - Write
---

You write the data upgrade a release needs (#56). A tester who installs this release keeps their `profile/` and `jobs/`: data written by the previous release is upgraded on the first start by the steps in `src/door/core/migrations.py`. Your job is to make sure the steps this release needs exist, and that no step is written that is not needed.

## Input

- `previous_tag`: the last release's tag, `vX.Y.Z` (none = the first release: report "no step needed: no earlier release" and stop).
- `new_version`: the version being released, `X.Y.Z` (a higher `X` than the tag's is a major bump: see the rules).
- `prs`: the PRs merged since that tag (number, title, and their bodies' "Removed or renamed" sections).

## The rules (from `src/door/core/migrations.py`'s docstring)

- Each of `profile/` and `jobs/` has its own data version, `<folder>/.data_version`, written `<major>.<n>`: the app's major version and the number of steps applied within it. A folder's current version is the app's major and the length of its list, `PROFILE_STEPS` or `JOBS_STEPS`. Every folder is stamped when it is created, so the file is the truth.
- A step is `Step(name, run)`, where `run(folder: Path)` moves that folder from N to N+1 and changes nothing outside it. A change touching both folders is two steps, one per list.
- **Never across a major version.** Data from an older major is refused, not upgraded. When the release bumps the major (`X` of `X.Y.Z`), write no step: empty both lists (keep `tests/data_versions/`: the gate checks that the older major's samples are refused untouched, and `/dev-release` deletes them after the tag, Step 6b), and report "major bump: lists emptied, <previous major>.x data is not opened". The release notes say so.
- **Never in a patch.** A patch release (`X.Y.Z` → `X.Y.(Z+1)`) changes no stored data. If `new_version` is a patch and you find a step is needed, write it anyway and say at the top of your report: "a step is needed: release X.(Y+1).0, not a patch".
- **Only between releases.** A step goes from the shape the previous tag wrote to the shape `main` writes. A shape that lived only on `main` between the two never gets a step.
- Steps are never edited or deleted once released. You only append.
- `name` is in a user's words, since the release notes and the error line show it ("templates come from the code").

## Step 1 — What changed

On a branch `release/data-<version or date>` from `main`:

1. Read `src/door/core/stored.py`'s `INVENTORY` at `main` and at the tag (`git show <tag>:src/door/core/stored.py`; a tag before #56 has none: read `docs/data.md` and the writers instead). For each stored file, diff what describes it between the tag and `main`:
   - the model or format named in its entry (`Profile` in `core/profile_loader.py`, a company entry in `core/companies.py`, a ledger entry in `core/tracker.py`, history, the story bank's sections, run records, `skill_aliases.json`, …): `git diff <tag>..main -- <file>`;
   - its location (a renamed or moved file);
   - the code-owned files (`profile.example/` templates and fonts; `core/templates.py`).
2. For each difference, find the PR that made it (`git log <tag>..main --format='%h %s' -- <file>`, then `gh pr list --search <sha> --state merged`) and read its body and diff. Sort it:
   - **new optional field or file** (a default exists, old data reads fine): no step;
   - **rename** (`sectors` → `preferences`): move the value to the new name;
   - **removal**: drop the key or file, so the strict model (`extra="forbid"`) accepts the old data;
   - **reshape** (a type, a nesting, an id format): convert;
   - **only on main** (added and changed or removed after the tag): no step.

## Step 2 — Prove it, test-first

Only if Step 1 found something a step must do.

1. **Red.** In `tests/core/test_migrations_unit.py` (or `tests/core/migrations/` once there are several), one test per folder whose step you write:
   - the previous release's saved data goes in: `tests/data_versions/<X.Y.Z>/` (#57) when it exists, else a folder written in the tag's shape inside the test;
   - this release's shape comes out, and `Profile` (or the format's own reader on `main`) accepts it.
   Run the tests and keep the red run's failures.
   The release gate (`poetry run pytest tests/release -m release -n 0`) upgrades every saved release under `tests/data_versions/` and compares what the current tools read back with its `expected.json`: any difference fails unless a step that ran lists it in `Step(..., changes=(...))`, globs over the dotted paths of `expected.json` (e.g. `show_profile.config.sectors`), each covering everything under it. List exactly what the step changes on purpose, nothing broader.
2. **Green.** Append at most one `Step` to `PROFILE_STEPS` and at most one to `JOBS_STEPS`; one step can make several changes to its folder. Keep each change small.
3. If `stored.py` gained or lost a file, `tests/core/test_stored_unit.py` must still pass.
4. Run `./scripts/run-test.sh` (the whole offline suite) and, when `tests/data_versions/` exists, #57's release test.
5. Commit (`data: upgrade <folder> from <previous tag>: <step name>`) and open the PR with `/dev-pr`.

## Output

```
## Data migration report
Previous release: <tag>
Checked:
- <stored file or model>: <unchanged | new optional field X: no step | renamed X → Y: step | removed X: step | only on main: no step> (#<PR>)
- ...
Steps: profile <n → n+1: "<name>"> | none; jobs <...> | none
Release note line: Your data is upgraded on first start: <what each step does, in a user's words>   (omit when no step)
Tests: <test names>; red run: <command → failures>; suite: <passed>/<failed>
PR: <url> | no step needed
```

Never change a released step, the version files of real data, or anything under `profile/` or `jobs/` of the checkout.
