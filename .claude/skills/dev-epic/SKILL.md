---
name: dev-epic
description: Work through an epic issue under /goal — resolve its sub-issues one by one, each in its own incremental pull request watched until green, file what is found on the way as new sub-issues, and tick the epic's checkboxes, until every sub-issue is implemented and every box is checked. Invoked with /dev-epic <epic_issue_number>, best under the /goal line it prints.
---

You are working through an epic issue of The other door. The epic's number is the argument. **Repo constants**: `owner: synesenom`, `repo: the-other-door`, `base: main`.

**Decision policy**: as `/dev-resolve`: decide alone; a question that is the maintainer's goes to the `decider` agent (CLAUDE.md "Decisions"), and only its CANNOT DECIDE goes to the user.

---

## How this runs under /goal

`/goal` is a Claude Code command the user types; a skill cannot set it. So this skill is built to be **one step per turn**, safe to run again and again: each run reads the state from GitHub and `thoughts/epic/<N>.md`, does the next piece of work, and ends with the status table (Step 6). The user starts it once with:

```
/goal Epic #<N> is done: every sub-issue of #<N> and of its sub-epics (including ones added while working) is closed as completed, closed as not planned with its box ticked and noted, or has an open pull request that closes it with every check green and no merge conflict; and the body of #<N> has no unchecked "- [ ]" box. Prove it with the /dev-epic status table printed this turn. Each turn, continue with /dev-epic <N>. Or stop after 60 turns, counted in the table's Turn line.
```

The goal's evaluator reads only the conversation, never GitHub, so **every turn ends with the status table**: it is the evidence the goal is judged on. If the skill was invoked without that goal set (the user typed `/dev-epic <N>` alone), do the first step anyway and print the `/goal` line above, filled in, at the end, so the user can keep it going.

"Implemented" means: a pull request that closes the sub-issue is open, green and merges cleanly, or it was merged (the sub-issue is closed as completed). Merging is the maintainer's: never merge, approve or enable auto-merge.

---

## Step 1: Read the epic

Run in parallel:

- `mcp__github__issue_read` (`method: get`) on #`<N>`: title, body, labels, state.
- `mcp__github__issue_read` (`method: get_sub_issues`) on #`<N>`: every sub-issue, its number, title and state, in GitHub's order.
- Read `thoughts/epic/<N>.md` if it exists (the state of earlier turns).

For each open sub-issue, find its pull request: `mcp__github__issue_read` (`method: get`) on it gives `closed_by_pull_requests`; when that is missing or empty, fall back to `gh api -X GET search/issues -f q='repo:synesenom/the-other-door is:pr is:open "Closes #<sub>"'` before treating it as PR-less. Read its checks (`mcp__github__pull_request_read`, `method: get_check_runs`) and whether it is mergeable (`method: get`).

A sub-issue closed as not planned is done: its box is ticked with ` — not planned` (Step 5), never worked.

If the epic is closed, or has no sub-issues and no unchecked box, print the status table and stop: the goal is met (or has nothing to do), say which.

---

## Step 2: Every box has a sub-issue

Read the body's checkboxes (`- [ ]` and `- [x]`). Each unchecked box must map to a sub-issue: by a `#<sub>` on its line, or by its words matching a sub-issue's title. A box that maps to none is work the epic asks for that no issue tracks: file it (`mcp__github__issue_write`, `method: create`, a title from the box, a body that quotes the box and links the epic), attach it (`mcp__github__sub_issue_write`, `method: add`, `sub_issue_id` the new issue's `id`, not its number), and add ` (#<sub>)` to the box's line in the epic body, so the next turn maps it by number. A box that is not work (a note, a question already answered in the issue's comments) goes to the `decider`: tick it with a one-line comment on the epic saying why, or file it.

---

## Step 3: Keep the open pull requests green first

Before new work, look after the PRs this skill opened (`thoughts/epic/<N>.md`) as `/dev-pr` Step 7 and CLAUDE.md "Pull requests" say: a failing check is read, fixed test-first on its branch, pushed; a conflict with `main` is merged and resolved; a review comment is addressed or put to the user. Do this on the PR's own branch (`git switch <branch>`), and come back. PR events arrive as turns of their own while it is subscribed: handle such a turn here, then go on.

A PR merged since the last turn: its sub-issue closes on GitHub; update the state file. A PR closed without merging: its sub-issue is open again with no PR; say so in the table and pick it again in Step 4 only after reading why it was closed (the comments); if the maintainer closed it on purpose, put it to the user.

---

## Step 4: The next sub-issue

Pick the first open sub-issue, in GitHub's order, that has no PR yet and is not blocked:

- **Blocked** means its body or comments say it depends on another sub-issue that is not merged yet. If it depends on one whose PR is open, it is not blocked: stack it (below). If it needs a decision only the maintainer can take (the `decider` said CANNOT DECIDE), record the question in the state file, mark it `blocked: question` and pick the next one; ask with AskUserQuestion only when nothing else is left to do (it blocks the turn, and under `claude -p` nobody answers).
- **Sub-issue that is itself an epic** (it has sub-issues): work its sub-issues with the same steps, depth first, their rows indented under it in the table; it counts as implemented when they all are and its own boxes are ticked.

Resolve it as `/dev-resolve <sub>` does, Steps 1–3 (assess, research and plan when complex, implement test-first, validate), on a fresh branch:

```bash
git fetch origin main
git switch -c <type>/<sub>-<slug> origin/main          # independent: from main
git switch -c <type>/<sub>-<slug> origin/<dep-branch>   # stacked on an open sibling PR
```

The branch name follows `/dev-pr`'s table. A branch the session's own instructions name (a cloud session's fixed branch) wins over this; then the PRs of the epic go out one at a time, the next only after the last merged.

A stacked sub-issue is validated against its dependency branch: the `issue-validator` gets `base_branch: <dep-branch>`, not `main`, so the dependency's commits are not judged as this one's.

**Gaps** (CLAUDE.md "Gaps"): before opening the PR, spawn `gap-reviewer` with `base_branch: main` (or the dependency branch) and the sub-issue. Each gap is fixed in this PR (small, in scope) or filed. A filed gap **within the epic's goal** is attached to the epic as a new sub-issue (`mcp__github__sub_issue_write`, `method: add`), and so joins the queue and the goal; a gap outside it is filed on its own, not attached, and named in the report. Attach only what the epic's own text asks for or makes necessary: the goal must not grow without end.

On validation PASS, open the PR with `/dev-pr` (branch check, merge `main`, push, its body format with `Closes #<sub>` and a line `Part of #<N>`, subscribe). A stacked PR's body also says `Depends on #<dep-pr>` and its test plan says the diff holds the dependency's commits until that one merges. On FAIL after two attempts, open no PR: record the diagnosis in the state file, comment it on the sub-issue, mark it `failed`, and move to the next one; once nothing else is left, put each failed one to the user with AskUserQuestion (try again with their hint, or leave it), since the goal cannot be met without it.

One sub-issue per turn: end the turn after its PR is open (Step 6). The next turn starts with Step 1 again and so picks up the CI results.

**Waiting.** When nothing is left to start (every remaining sub-issue has a PR with checks still running, or is blocked, failed or waiting for a merge), do not end turns that only re-read GitHub: the goal loop would spin, and Claude Code stops a loop that makes no tool use. Instead, before ending the turn, start a background command that waits for the running checks (a loop on `gh pr checks <pr> --watch`, or a Monitor on the check runs); a turn that ends with background work running defers the goal's check, and the result arrives as the next turn. When only the maintainer can move things on (merges to wait for, questions or failures to answer), say so in the table's Next line, name what they must do, and tell them to `/goal clear` or answer; do not loop.

---

## Step 5: Tick the boxes

Tick a box (`- [ ]` → `- [x]`, adding ` — #<pr>` after it) only when its sub-issue is implemented (open, green and mergeable PR, or merged), or with ` — not planned` when it was closed as not planned. Edit the body with `mcp__github__issue_write` (`method: update`), changing only those boxes: re-read the body first and keep every other character as it is, since the maintainer may have edited it. Untick a box whose PR went red or was closed unmerged.

---

## Step 6: State and status table

Write `thoughts/epic/<N>.md`: the turn count (one more each run), per sub-issue its branch, PR, state (`todo`, `in progress`, `PR open`, `PR red`, `merged`, `failed`, `blocked: <why>`, `not planned`), the open questions, and the last turn's notes. Then end the turn with:

```
Epic #<N> — <title>        Turn <k>/60
| Sub-issue | Title | PR | Checks (green/red/running) | Mergeable | State |
|-----------|-------|----|--------|-----------|-------|
| #12       | ...   | #40 | green | yes | PR open |
|   ↳ #15   | ...   | —  | —     | —   | todo |
...
Sub-issues: <done>/<total> implemented   New this turn: #.., #..
Epic boxes: <checked>/<total> checked    Unchecked: <list, or none>
Next: <what the next turn does, or "goal met">
```

The counts are from GitHub as read this turn, never remembered. When every sub-issue is implemented and no box is unchecked, say "goal met" in one line, with the PRs left for the maintainer to merge.
