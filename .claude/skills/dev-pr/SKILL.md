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

- `git log origin/main..HEAD --oneline` — list commits being proposed.
- `git diff origin/main...HEAD --stat` — list changed files.

From the commits and diff, draft:

- **Title**: one concise sentence (≤ 70 chars) summarising what the branch does. Prefer "add", "fix", "update" over passive voice.
- **Body** (markdown):
  ```
  ## Summary
  <2–4 bullet points covering what changed and why>

  ## Test plan
  - [ ] `./scripts/run-test.sh` passes (offline suite)
  - [ ] Relevant new tests added (list them if applicable)
  - [ ] Manual smoke test if behaviour is user-visible

  <session URL: https://claude.ai/code/session_01Szd7ojDtFzViocQeVTe2zi>
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
