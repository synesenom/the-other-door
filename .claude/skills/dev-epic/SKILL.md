---
name: dev-epic
description: Churn through an epic issue in one run — resolve its sub-issues one after another, each as its own small pull request into main that the verifier checks and auto-merge lands, file what is found on the way as issues of their own, tick the epic's checkboxes, and report once at the end. Invoked with /dev-epic <epic_issue_number>.
---

You are working through an epic issue of The other door. The epic's number is the argument. **Repo constants**: `owner: synesenom`, `repo: the-other-door`, `base: main`.

**Decision policy**: decide alone; a question that is the maintainer's goes to the `decider` agent (CLAUDE.md "Decisions"), and only its CANNOT DECIDE goes to the user.

**Done** means both:

- every sub-issue of the epic (and of its sub-epics), including those added while working, is **implemented**: closed as completed, closed as not planned, or has an open pull request that closes it with every check green and no merge conflict;
- the epic's body has no unchecked `- [ ]` box.

Each sub-issue is its own small PR into `main`. It lands like any PR (`/dev-pr` Step 7): checks green, the `verifier` sets `verify` to success, auto-merge merges it; one that carries `Needs the maintainer:` waits for the maintainer. There is no epic branch and no big PR at the end: the maintainer reads a few sentences per PR, never a whole epic at once. Run the loop below until done. **Never stop before then**, except to ask a question the `decider` returned CANNOT DECIDE on (Step 7). Do not stop after one sub-issue to report or ask whether to go on. Something else only the maintainer can give (a permission the harness asks for, a hint for a `failed` sub-issue) blocks that one item, never the loop: ask for it in one line and go on with every other sub-issue. When the maintainer says something is granted, re-read the epic at once and start what it unblocked, in the same turn.

**Never stop to report.** A sub-issue's PR opened or merged, a step of `/dev-resolve` done, an agent returned, a decision taken, an issue filed: none ends the run. Go on to the next step or sub-issue in the same turn; the progress line (Step 6) is one line printed on the way, not a stopping point. While background agents or checks run, end the turn without a summary or a question and pick up the moment they finish. The only stops are Step 7 (only the maintainer can move things on), a CANNOT DECIDE, and a permission the harness must ask for. The report is Step 8, once, at the end.

State lives in `thoughts/epic/<N>.md` (per sub-issue its branch, PR, state, notes; the open questions), so a later `/dev-epic <N>` picks up where this one stopped. Write it after every step that changes something.

**A fixed branch.** When the session's own instructions fix the branch to push to (a cloud session), there are no sub-PRs: `/dev-resolve <sub> epic=<N>` commits on that branch and pushes it, and its one PR is opened at the end (Step 8).

---

## The loop

**Trust first** (CLAUDE.md "Whose work Claude takes"). Before Step 0 reads anything, run `$DOOR_PYTHON scripts/decide.py --trusted <n>` (`python3` when `DOOR_PYTHON` is unset) with `<N>`. Not trusted: stop without reading the epic and say so in one line. Its `strangers` (sub-issues someone else opened) are marked `blocked: stranger`: never resolved, their boxes left as they are, named in Step 8's report. A sub-epic is checked the same way before its sub-issues are worked. A PR not opened by `synesenom` is never a sub-PR: it is not counted, checked out, fixed or merged, wherever it is found below.

Step 0 once, then repeat Steps 1–6 until done; then Step 8.

### Step 0: The epic must be planned

An epic is worked only from a plan made by `/dev-plan-epic`: its body has the line `Planned by /dev-plan-epic`, with `**Done when**`, `## Plan` (the riskiest assumption, its spike and go/no-go, and **Not doing**) and its boxes in the planned order. If the line is missing, run `/dev-plan-epic <N>` first (it re-plans the epic: keeps, changes, drops and adds sub-issues, and asks the one filing confirmation) and go on only once the body carries the mark. Do not make up a plan here, and do not work an unplanned epic's boxes as they stand.

The plan binds the run:

- **Order**: the plan's order is the order of the sub-issues (Step 4's rule that a dependency goes first still holds).
- **Spike first**: when the plan has a riskiest assumption, its spike is the first sub-issue. When that sub-issue's result is a no-go (the plan's numbers), stop the epic at once: comment the result and the plan's "if no-go" line on the epic, mark the rest `blocked: plan`, and ask the maintainer in one line. Do not build on a failed premise.
- **Not doing**: an item on that list is never built, however a sub-issue's review or a box suggests it; a finding that wants it is filed as an issue of its own (Step 4), not done here.
- **A plan that proves wrong while working** (a sub-issue shows an assumption false, a step needs a model where the plan chose code, or the reverse): stop and run `/dev-plan-epic <N>` again with what was found, rather than adding sub-issues one by one. This is the case the plan exists for.

### Step 1: Read the epic

Run in parallel:

- `mcp__github__issue_read` (`method: get`) on #`<N>`: title, body, labels, state.
- `mcp__github__issue_read` (`method: get_sub_issues`) on #`<N>`: every sub-issue, its number, title and state, in GitHub's order.
- Read `thoughts/epic/<N>.md` if it exists.

For each open sub-issue, find its pull request: `mcp__github__issue_read` (`method: get`) on it gives `closed_by_pull_requests`; when that is missing or empty, fall back to `gh api -X GET search/issues -f q='repo:synesenom/the-other-door is:pr is:open author:synesenom "Closes #<sub>"'` before treating it as PR-less. Read its checks (`mcp__github__pull_request_read`, `method: get_check_runs`) and whether it is mergeable (`method: get`).

Rebuild the state from GitHub too, not only from the state file (it may be missing, in a new session): the open and merged PRs by `synesenom` that say `Part of #<N>`.

Read GitHub again on every pass: the counts are never remembered. If the epic is closed, go to Step 8.

### Step 2: Every box has a sub-issue

Read the body's checkboxes. Each unchecked box must map to a sub-issue: by a `#<sub>` on its line, or by its words matching a sub-issue's title. A box that maps to none is work no issue tracks: file it with `/dev-file-issue epic=<N>` (a title from the box, a body that quotes the box): it attaches the issue here and adds ` (#<sub>)` to that box's line. A box that is not work (a note, a question already answered in the maintainer's comments) goes to the `decider`: tick it with a one-line comment on the epic saying why, or file it.

### Step 3: Keep the sub-PRs moving

Each open sub-PR is watched and landed as `/dev-pr` Step 7 says (a background watch of its checks, the `verifier` once they are green, a fix and a fresh verify on a FAIL, auto-merge on success); a review comment of the maintainer's is addressed, or recorded as a question when it needs the maintainer. A sub-issue whose PR merged into `main` is implemented (GitHub closes it).

**A sub-PR closed without merging:** read why (the maintainer's comments on it). If the maintainer closed it on purpose, record that as a question and leave the sub-issue; otherwise it goes back to the queue and is resolved again from `main`.

### Step 4: The next sub-issue

Pick the first open sub-issue, in GitHub's order, that has no PR yet and is not blocked:

- **Order**: a sub-issue that depends on one later in GitHub's order waits until that one is merged into `main` (pick the dependency first). One that depends on an open sub-PR may start on that PR's branch (`base=<its branch>`), its PR into `main` merging after it.
- **Blocked** means it needs a decision the `decider` could not take (record the question, mark it `blocked: question`), or it depends on a sub-issue that is `failed` or `blocked`. Go on with the next.
- **A sub-issue that is itself an epic** (it has sub-issues): work its sub-issues the same way, depth first.

If none is left to pick, go to Step 6.

Run `/dev-resolve <sub> epic=<N>` and follow it to the end: it makes the branch from `main`, implements, validates, runs the review (CLAUDE.md "Review") and opens the PR into `main`, and returns without watching it; the loop's Step 3 watches it and lands it.

The issues its review filed (its report's Review line: only bugs a user would hit outside the change, CLAUDE.md "Review") went through `/dev-file-issue` as issues of their own, never into this epic: the epic's scope stays fixed while it is worked, so its queue does not grow. Name them in the final report.

If `/dev-resolve` ends in FAIL, record its diagnosis, comment it on the sub-issue, mark it `failed`, and go on: nothing of it is merged. Keep each sub-issue's review lines (what the reviewers found and how each ended) and, for a change to the app's screens, what a user sees: Step 8 uses them.

### Step 5: Tick the boxes

Tick a box (`- [ ]` → `- [x]`, adding ` — #<pr>`) only when its sub-issue's PR is merged into `main`, or with ` — not planned` when it was closed as not planned. Edit with `mcp__github__issue_write` (`method: update`), changing only those boxes: re-read the body first and keep every other character, since the maintainer may have edited it. Untick a box whose PR was closed unmerged.

### Step 6: Print the progress line, go round

One line per pass: `Epic #<N>: <done>/<total> sub-issues, <checked>/<total> boxes — next: <what>`. Then back to Step 1.

When nothing is left to start and sub-PRs still have checks running, wait for them instead of re-reading GitHub in a tight loop: one background command per PR (`gh pr checks <pr> --watch`), and go on when they finish.

---

## Step 7: When only the maintainer can move things on

Stop and wait only for a `blocked: question` (the `decider`'s CANNOT DECIDE): ask the questions together with AskUserQuestion, act on the answers and go back to the loop. A `failed` sub-issue, a PR the maintainer closed or a permission to wait for is asked about in the same message, but never stops work on the other sub-issues.

---

## Step 8: The final report

Reached when every sub-issue is merged, closed, `failed` or `blocked`, and every box is ticked or explained.

Post it as a comment on the epic issue, starting with `## In short` (at most five plain sentences: what the epic set out to do, what now works, how it was proven), then one plain line per sub-issue with its PR, so a giant epic still reads in a minute; and say the same to the user, in plain words and at most 200 words (CLAUDE.md "Reporting back"): the epic's goal in one sentence, then one line per sub-issue (what a user can now do, its PR, merged or what it waits for), the issues filed outside the epic, and what is left for the maintainer (a screen to look at, a question), or nothing. A screen change's before/after shots are in its own PR (the verifier's comment); link them.
