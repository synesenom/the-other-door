---
name: dev-epic
description: Churn through an epic issue in one run — resolve its sub-issues one after another, each in its own incremental pull request kept green, file what is found on the way as new sub-issues, and tick the epic's checkboxes, until every sub-issue is implemented and every box is checked. Invoked with /dev-epic <epic_issue_number>.
---

You are working through an epic issue of The other door. The epic's number is the argument. **Repo constants**: `owner: synesenom`, `repo: the-other-door`, `base: main`.

**Decision policy**: as `/dev-resolve`: decide alone; a question that is the maintainer's goes to the `decider` agent (CLAUDE.md "Decisions"), and only its CANNOT DECIDE goes to the user.

**Done** means both:

- every sub-issue of the epic (and of its sub-epics), including those added while working, is **implemented**: closed as completed, closed as not planned, or has an open pull request that closes it with every check green and no merge conflict;
- the epic's body has no unchecked `- [ ]` box.

Merging is the maintainer's: never merge, approve or enable auto-merge. Run the loop below until done, or until only the maintainer can move things on (Step 7). Do not stop after one sub-issue to report or ask whether to go on.

State lives in `thoughts/epic/<N>.md` (per sub-issue its branch, PR, state, notes; the open questions), so a later `/dev-epic <N>` picks up where this one stopped. Write it after every step that changes something.

---

## The loop

Repeat Steps 1–6 until done; then Step 8.

### Step 1: Read the epic

Run in parallel:

- `mcp__github__issue_read` (`method: get`) on #`<N>`: title, body, labels, state.
- `mcp__github__issue_read` (`method: get_sub_issues`) on #`<N>`: every sub-issue, its number, title and state, in GitHub's order.
- Read `thoughts/epic/<N>.md` if it exists.

For each open sub-issue, find its pull request: `mcp__github__issue_read` (`method: get`) on it gives `closed_by_pull_requests`; when that is missing or empty, fall back to `gh api -X GET search/issues -f q='repo:synesenom/the-other-door is:pr is:open "Closes #<sub>"'` before treating it as PR-less. Read its checks (`mcp__github__pull_request_read`, `method: get_check_runs`) and whether it is mergeable (`method: get`).

Read GitHub again on every pass: the counts are never remembered. If the epic is closed, go to Step 8.

### Step 2: Every box has a sub-issue

Read the body's checkboxes. Each unchecked box must map to a sub-issue: by a `#<sub>` on its line, or by its words matching a sub-issue's title. A box that maps to none is work no issue tracks: file it (`mcp__github__issue_write`, `method: create`, a title from the box, a body that quotes the box and links the epic), attach it (`mcp__github__sub_issue_write`, `method: add`, `sub_issue_id` the new issue's `id`, not its number), and add ` (#<sub>)` to the box's line in the epic body. A box that is not work (a note, a question already answered in the comments) goes to the `decider`: tick it with a one-line comment on the epic saying why, or file it.

### Step 3: Keep the open pull requests green

Look after the PRs this skill opened as `/dev-pr` Step 7 and CLAUDE.md "Pull requests" say: a failing check is read, fixed test-first on its own branch (`git switch <branch>`), pushed; a conflict with `main` is merged and resolved; a review comment is addressed, or recorded as a question when it needs the maintainer. PR events that arrive while you work are handled here on the next pass.

A PR closed without merging: read why (its comments). If the maintainer closed it on purpose, record it as a question and leave the sub-issue; otherwise it goes back to the queue.

### Step 4: The next sub-issue

Pick the first open sub-issue, in GitHub's order, that has no PR yet and is not blocked:

- **Blocked** means it depends on another sub-issue that has no PR yet (pick that one first), or it needs a decision the `decider` could not take: record the question, mark it `blocked: question`, and go on with the next.
- **A sub-issue that is itself an epic** (it has sub-issues): work its sub-issues the same way, depth first.

If none is left to pick, go to Step 6.

Resolve it as `/dev-resolve <sub>` does, Steps 1–3 (assess, research and plan when complex, implement test-first, validate), on a fresh branch named by `/dev-pr`'s table:

```bash
git fetch origin main
git switch -c <type>/<sub>-<slug> origin/main          # independent: from main
git switch -c <type>/<sub>-<slug> origin/<dep-branch>   # depends on a sibling whose PR is open: stack on it
```

A stacked sub-issue is validated and reviewed against its dependency branch (`base_branch: <dep-branch>`), so the dependency's commits are not judged as its own. A branch the session's own instructions fix (a cloud session's single branch) wins over this: then the epic's PRs go out one at a time, the next only once the last is merged, and Step 7 applies while waiting.

**Review** (CLAUDE.md "Review"): before opening the PR, spawn the reviewers it names (`gap-reviewer`, `simplicity-reviewer`, and `design-reviewer` when the app's screens or `docs/design/` changed) with the base branch and the sub-issue. Each finding is fixed in this PR (small, in scope) or filed. A filed finding **within the epic's goal** is attached to the epic as a new sub-issue, and so joins the queue; one outside it is filed on its own, not attached, and named in the final report. Attach only what the epic's own text asks for or makes necessary, so the queue does not grow without end.

On validation PASS, open the PR with `/dev-pr` (branch check, merge `main`, push, its body format with `Closes #<sub>` and a line `Part of #<N>`, subscribe), but do not stay in its Step 7 watch: the loop's Step 3 watches it. A stacked PR's body also says `Depends on #<dep-pr>`. On FAIL after two attempts, open no PR: record the diagnosis, comment it on the sub-issue, mark it `failed`, and go on.

### Step 5: Tick the boxes

Tick a box (`- [ ]` → `- [x]`, adding ` — #<pr>`) only when its sub-issue is implemented, or with ` — not planned` when it was closed as not planned. Edit with `mcp__github__issue_write` (`method: update`), changing only those boxes: re-read the body first and keep every other character, since the maintainer may have edited it. Untick a box whose PR went red or was closed unmerged.

### Step 6: Print the progress line, go round

One line per pass: `Epic #<N>: <done>/<total> sub-issues, <checked>/<total> boxes — next: <what>`. Then back to Step 1.

When nothing is left to start and PRs still have checks running, wait for them instead of re-reading GitHub in a tight loop: one background command per PR (`gh pr checks <pr> --watch`), and go on when they finish.

---

## Step 7: When only the maintainer can move things on

When everything left is a merge to wait for, a `blocked: question`, a `failed` sub-issue or a PR the maintainer closed: ask the questions together with AskUserQuestion (for a failed one: try again with their hint, or leave it). Act on the answers and go back to the loop. If what is left is only merges, stop and report (Step 8): merging is theirs, and `/dev-epic <N>` continues afterwards.

---

## Step 8: Final report

```
Epic #<N> — <title>
| Sub-issue | Title | PR | Checks | Mergeable | State |
|-----------|-------|----|--------|-----------|-------|
| #12       | ...   | #40 | green | yes | PR open |
|   ↳ #15   | ...   | #41 | green | yes | PR open |
...
Sub-issues: <done>/<total> implemented   Added on the way: #.., #..
Epic boxes: <checked>/<total> checked    Unchecked: <list, or none>
Filed outside the epic: #.., #..
Left for you: <PRs to merge, in order (stacked ones after their base); questions; or nothing>
```

Then at most 10 short bullets (CLAUDE.md "Reporting back"): what was done, each review finding and which way it went.
