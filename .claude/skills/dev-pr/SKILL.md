---
name: dev-pr
description: Merge latest main into the current branch, push, open a pull request, and start listening to CI and review activity. Invoked with /dev-pr [base=<branch>] [epic=<number>].
---

You are preparing and opening a pull request for The other door. Follow all steps in order.

**Repo constants**: `owner: synesenom`, `repo: the-other-door`, `base: main`.

Optional arguments, which `/dev-resolve` and `/dev-epic` pass on:

- `base=<branch>`: the branch this one was built on (in an epic, its epic branch). Everything below that reads the change uses `origin/<base>` (shown as `<FROM>`; `origin/main` without it), so the base's commits are not described as this change's.
- `target=<branch>`: the branch the PR goes into (default `main`; in an epic, the epic branch). Step 2 merges `origin/<target>` instead of `origin/main`, and the body is for a reviewer of that branch, not a release note: it may leave out `## For users` when it has nothing a user would notice on its own.
- `epic=<number>`: the body adds `Part of #<epic>`, and the run stops after Step 6: the caller watches.
- `final=true` (with `epic`; the PR is the epic branch into `main`): the base is `main`, `<FROM>` is `origin/main`, the body gets `Closes` lines, the `## Summary` and the `## What it looks like` that `/dev-epic` Step 8 names, and the run goes on to Step 7: the epic PR is watched here.

---

## Step 1: Guard checks

Run these in parallel:

- `git status --porcelain` — if there are uncommitted changes, tell the user to commit or stash them first and **stop**.
- `git branch --show-current` — record the current branch name as `BRANCH`. If it is `main`, tell the user PRs must come from a feature branch and **stop**.

### Branch name

A branch is named `<type>/<slug>` (with an issue: `<type>/<issue>-<slug>`), `<slug>` two to five lowercase words joined by `-`. `<type>` is the kind of change, which `/dev-release` reads to sort it into the release notes:

| Type | For |
|------|-----|
| `feat` | something a user can do that they could not before |
| `fix` | a bug a user could hit |
| `change` | existing behaviour a user notices working differently, or something removed |
| `docs` | documentation only |
| `refactor`, `test`, `ci`, `chore` | internal: no user would notice |

Dependabot's `dependabot/...` branches and the skills' own (`feat/country-<cc>`, `feat/profession-...`, `release/vX.Y.Z`, `fix/scraper-...`) already follow it. If `BRANCH` has no such prefix, or its prefix does not match what the commits do (`git log <FROM>..HEAD --oneline`), propose a name with AskUserQuestion (the proposal first, "Keep <BRANCH>" second). On a new name, and only if the branch was never pushed (`git ls-remote --heads origin <BRANCH>` is empty), `git branch -m <new>` and use it as `BRANCH`; a pushed branch keeps its name and the body's **Type** line says the kind.

---

## Step 2: Merge latest main

```bash
git fetch origin <target>   # main without `target`
git merge origin/<target> --no-edit
```

If the merge produces conflicts, resolve them keeping both sides' intent, run the tests the conflicting files touch, and commit the merge. Ask the user only if a conflict needs a decision the `decider` agent cannot make (CLAUDE.md "Decisions").

---

## Step 3: Push

```bash
git push -u origin <BRANCH>
```

Retry up to 4 times with exponential backoff (2 s, 4 s, 8 s, 16 s) on network failure. On persistent failure tell the user and **stop**.

---

## Step 4: Draft the PR title and body

Run these in parallel to gather context:

- `git log <FROM>..HEAD --format='%h %s%n%b'` — the commits being proposed, with their bodies (`closes #N` names the issues).
- `git diff <FROM>...HEAD --stat` — the changed files.
- `git diff <FROM>...HEAD` — read it: the body says what the change does, not what the commit subjects guess.
- For each issue named: `gh issue view <N> --json title,body` — why the change was wanted.

From these, draft:

- **Title**: one concise sentence (≤ 70 chars) saying what the branch does, in a user's words when they would notice it ("Phone: pair again from Settings", not "refactor serve_policy"). Active voice: "add", "fix", "show".
- **Body** (markdown). This body is the source of the release notes: `/dev-release` reads it months later, with no other context, so it must stand on its own.
  ```
  **Type**: feat | fix | change | docs | internal
  Closes #<N>   (one line per issue; leave out if none)
  Part of #<epic>   (only with `epic`)

  ## For users
  <What someone using The other door will notice, in their words and with no code names: what they can now do, what works differently, what stopped going wrong, what was removed. One to four bullets, each one sentence a release note can take as is. For internal work: "Nothing a user would notice.">

  ## Changes
  <What changed and why, for a reviewer: the parts touched (modules, commands, tools, screens, config keys, docs), the decisions taken and the alternatives left out. As many bullets as the change needs.>

  ## Removed or renamed
  <Every command, option, tool, config key, screen or behaviour removed or renamed, with what replaces it, if anything. Leave out the section when there is none.>

  ## Test plan
  - [x] `./scripts/run-test.sh` passes (offline suite)   (tick only what was run)
  - [ ] <the new or changed tests, by file>
  - [ ] <a check the `verifier` can run: the CLI in a sandbox, the app on the test world, staging, the preview>

  Needs the maintainer: <anything else, one line each; it keeps `verify` pending>

  <the PR attribution lines this session's system reminder gives>
  ```
- The Test plan holds only boxes the verifier can run; whatever else needs a person goes on a `Needs the maintainer: …` line, never a box. A PR that changes `app/src/renderer/`, `app/src/web/`, `app/src/preview/` or `docs/design/` always carries `Needs the maintainer: look at it` (`scripts/decide.py` enforces it from the changed files) and before/after screenshots of each changed screen, embedded in the body as images (so they show on a phone). Every other PR merges itself once verified (Step 7).

---

## Step 5: Create the PR

Call `mcp__github__create_pull_request` with:
- `owner: synesenom`, `repo: the-other-door`
- `head: <BRANCH>`, `base: <target>` (`main` without `target`)
- `title` and `body` from Step 4

Record the PR number from the response.

---

## Step 6: Subscribe to PR activity

Call `mcp__github__subscribe_pr_activity` with the PR number from Step 5.

---

## Step 7: Report to the user

```
Branch:  <BRANCH>
PR:      #<number> — <title>
URL:     <html_url from create_pull_request response>
Watching: CI failures and review comments will arrive in this session.
```

Then keep watching until the PR is verified and merged, or waits on the maintainer (CLAUDE.md "Pull requests"):

1. After each push wait about 60 s (path-filtered workflows register late), then run `gh pr checks <n> --watch` with `run_in_background`; it wakes the session when it exits.
2. On exit read `gh pr view <n> --json mergeable,statusCheckRollup`: `--watch` cannot see a conflict (no `pull_request` run starts while a PR conflicts).
   - **CI failure**: read the failing job logs, find the root cause, fix it test-first on the branch, push, and go back to 1. A flaky failure is rerun once and named in the report. A fix that needs a decision goes to the `decider`.
   - **Merge conflict** (main moved): merge `origin/main`, resolve as in Step 2, push, and go back to 1.
   - **Review comment**: address it if unambiguous and non-breaking; otherwise ask the user first.
3. **Everything green, no conflict**: spawn the `verifier` on the head. It posts `verify`: when `scripts/decide.py <n>` says merge, run `gh pr merge <n> --auto --squash --match-head-commit <sha>` (it refuses a moved head, and merges at once when every requirement already holds); with a `Needs the maintainer:` line, report it in one line and leave it pending.
4. **The verifier FAILs**: rerun the implementer once with the verdict, push, and verify again. After a second FAIL, attack the premise before another fix: write down the one sentence both fixes assumed, and run one observation that would come out differently if it were false. Record the premise, the run and its result in a PR comment. If the run disproves it, make one fix built on what it found and verify again. If the premise holds, or that fix fails too, the PR goes to the session-start list with the premise, its test and both verdicts, and the run carries on.
5. **PR merged or closed**: call `mcp__github__unsubscribe_pr_activity` and report the final status.
