---
name: dev-pr
description: Merge latest main into the current branch, push, open a pull request, and start listening to CI and review activity. Invoked with /dev-pr.
---

You are preparing and opening a pull request for The other door. Follow all steps in order.

**Repo constants**: `owner: synesenom`, `repo: the-other-door`, `base: main`.

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

Dependabot's `dependabot/...` branches and the skills' own (`feat/country-<cc>`, `feat/profession-...`, `release/vX.Y.Z`, `fix/scraper-...`) already follow it. If `BRANCH` has no such prefix, or its prefix does not match what the commits do (`git log origin/main..HEAD --oneline`), propose a name with AskUserQuestion (the proposal first, "Keep <BRANCH>" second). On a new name, and only if the branch was never pushed (`git ls-remote --heads origin <BRANCH>` is empty), `git branch -m <new>` and use it as `BRANCH`; a pushed branch keeps its name and the body's **Type** line says the kind.

---

## Step 2: Merge latest main

```bash
git fetch origin main
git merge origin/main --no-edit
```

If the merge produces conflicts, list the conflicting files, tell the user to resolve them and re-run `/dev-pr`, then **stop**.

---

## Step 3: Push

```bash
git push -u origin <BRANCH>
```

Retry up to 4 times with exponential backoff (2 s, 4 s, 8 s, 16 s) on network failure. On persistent failure tell the user and **stop**.

---

## Step 4: Draft the PR title and body

Run these in parallel to gather context:

- `git log origin/main..HEAD --format='%h %s%n%b'` — the commits being proposed, with their bodies (`closes #N` names the issues).
- `git diff origin/main...HEAD --stat` — the changed files.
- `git diff origin/main...HEAD` — read it: the body says what the change does, not what the commit subjects guess.
- For each issue named: `gh issue view <N> --json title,body` — why the change was wanted.

From these, draft:

- **Title**: one concise sentence (≤ 70 chars) saying what the branch does, in a user's words when they would notice it ("Phone: pair again from Settings", not "refactor serve_policy"). Active voice: "add", "fix", "show".
- **Body** (markdown). This body is the source of the release notes: `/dev-release` reads it months later, with no other context, so it must stand on its own.
  ```
  **Type**: feat | fix | change | docs | internal
  Closes #<N>   (one line per issue; leave out if none)

  ## For users
  <What someone using The other door will notice, in their words and with no code names: what they can now do, what works differently, what stopped going wrong, what was removed. One to four bullets, each one sentence a release note can take as is. For internal work: "Nothing a user would notice.">

  ## Changes
  <What changed and why, for a reviewer: the parts touched (modules, commands, tools, screens, config keys, docs), the decisions taken and the alternatives left out. As many bullets as the change needs.>

  ## Removed or renamed
  <Every command, option, tool, config key, screen or behaviour removed or renamed, with what replaces it, if anything. Leave out the section when there is none.>

  ## Test plan
  - [x] `./scripts/run-test.sh` passes (offline suite)   (tick only what was run)
  - [ ] <the new or changed tests, by file>
  - [ ] <a manual check, when the behaviour is user-visible>

  <the PR attribution lines this session's system reminder gives>
  ```

---

## Step 5: Create the PR

Call `mcp__github__create_pull_request` with:
- `owner: synesenom`, `repo: the-other-door`
- `head: <BRANCH>`, `base: main`
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

Then end your turn and wait. When `<github-webhook-activity>` events arrive:

- **CI failure** — read the failing job logs via `mcp__github__get_job_logs`, diagnose the root cause, push a fix if it is clear and small, then re-arm by staying subscribed. If the fix is ambiguous or large, ask the user before touching code.
- **Review comment** — address it if unambiguous and non-breaking; otherwise ask the user first.
- **CI green + approved** — report "PR is ready to merge" and stop monitoring.
- **PR merged or closed** — call `mcp__github__unsubscribe_pr_activity` and report the final status.
