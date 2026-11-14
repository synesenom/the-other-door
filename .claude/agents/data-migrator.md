---
name: data-migrator
description: Write the upgrade step a release needs for the data the previous release wrote — diff everything `src/door/core/stored.py` names between the last tag and main, tell a rename from a removal from a new optional field by reading the PRs, and write at most one step per folder test-first, or report "no step needed" item by item. Spawned by the /dev-release skill before tagging; not for direct use. The prompt must include the previous tag and the merged PRs.
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
- `prs`: the PRs merged since that tag (number, title, and their bodies' "Removed or renamed" sections).

## The rules (from `src/door/core/migrations.py`'s docstring)

- Each of `profile/` and `jobs/` has its own data version, `<folder>/.data_version`. A folder's current version is the length of its list, `PROFILE_STEPS` or `JOBS_STEPS`.
- A step is `Step(name, run)`, where `run(folder: Path)` moves that folder from version N to N+1 and changes nothing outside it. A change touching both folders is two steps, one per list.
- **Every step is idempotent.** Run on data already in the new shape, it changes nothing: a missing version file is no proof of old data.
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
   - this release's shape comes out, and `Profile` (or the format's own reader on `main`) accepts it;
   - running the step again, and running it on data `main` writes, changes nothing.
   Run the tests and keep the red run's failures.
2. **Green.** Append at most one `Step` to `PROFILE_STEPS` and at most one to `JOBS_STEPS`; one step can make several changes to its folder. Keep each change small and guarded so it stays idempotent: check for the old shape before you touch anything.
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
