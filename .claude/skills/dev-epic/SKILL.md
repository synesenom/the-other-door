---
name: dev-epic
description: Churn through an epic issue in one run — resolve its sub-issues one after another on one epic branch (each in its own pull request into that branch, merged once green), file what is found on the way as issues of their own, tick the epic's checkboxes, then open one pull request from the epic branch into main with a plain summary and screenshots or a GIF of anything a user sees. Invoked with /dev-epic <epic_issue_number>.
---

You are working through an epic issue of The other door. The epic's number is the argument. **Repo constants**: `owner: synesenom`, `repo: the-other-door`, `base: main`.

**Decision policy**: decide alone; a question that is the maintainer's goes to the `decider` agent (CLAUDE.md "Decisions"), and only its CANNOT DECIDE goes to the user.

**Done** means both:

- every sub-issue of the epic (and of its sub-epics), including those added while working, is **implemented**: closed as completed, closed as not planned, or has an open pull request that closes it with every check green and no merge conflict;
- the epic's body has no unchecked `- [ ]` box.

A sub-issue's PR into the epic branch (below) is merged (squash) by you without asking once its checks are green and its review findings are dealt with. The epic branch's PR into `main` goes through the `verifier` and auto-merge like any PR (`/dev-pr` Step 7); one that changes screens waits for the maintainer's look and merge. Run the loop below until done. **Never stop before then**, except to ask a question the `decider` returned CANNOT DECIDE on (Step 7). Do not stop after one sub-issue to report or ask whether to go on. Something else only the maintainer can give (a permission the harness asks for, a hint for a `failed` sub-issue) blocks that one item, never the loop: ask for it in one line and go on with every other sub-issue. When the maintainer says something is granted, re-read the epic at once and start what it unblocked, in the same turn.

**Never stop to report.** A sub-issue's PR opened or merged, a step of `/dev-resolve` done, an agent returned, a decision taken, an issue filed: none ends the run. Go on to the next step or sub-issue in the same turn; the progress line (Step 6) is one line printed on the way, not a stopping point. While background agents or checks run, end the turn without a summary or a question and pick up the moment they finish. The only stops are Step 7 (only the maintainer can move things on), a CANNOT DECIDE, and a permission the harness must ask for. The report is Step 8, once, at the end.

State lives in `thoughts/epic/<N>.md` (the epic branch; per sub-issue its branch, PR, state, notes; the open questions), so a later `/dev-epic <N>` picks up where this one stopped. Write it after every step that changes something.

**The epic branch.** `epic/<N>-<slug>` (`<slug>` two to five words from the epic's title), made from `main` and pushed at the start (or found again from the state file or `git ls-remote --heads origin 'epic/<N>-*'`). Every sub-issue's branch starts from the epic branch's current tip and its PR targets the epic branch (`/dev-resolve <sub> epic=<N> base=<epic branch> target=<epic branch>`). A green sub-PR is squash-merged into the epic branch by you; the next sub-issue starts from the new tip. So the epic branch is always the sum of what is done, and it is the only branch that ever becomes a PR into `main` (Step 8). Never rebase or force-push it. `main` moving is handled by merging `origin/main` into the epic branch (Step 3).

**A fixed branch.** When the session's own instructions fix the branch to push to (a cloud session), that branch is the epic branch, and there are no sub-PRs: `/dev-resolve <sub> epic=<N>` commits on it (no `base`, no `target`), pushes it, and the epic branch's PR is opened at the end (Step 8).

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

Rebuild the state from GitHub too, not only from the state file (it may be missing, in a new session): the epic branch, the open PRs into it by `synesenom` that say `Part of #<N>`, and the PRs already merged into it (a sub-issue whose PR was merged into the epic branch is implemented, though GitHub keeps it open until the epic branch reaches `main`).

Read GitHub again on every pass: the counts are never remembered. If the epic is closed, go to Step 8.

### Step 2: Every box has a sub-issue

Read the body's checkboxes. Each unchecked box must map to a sub-issue: by a `#<sub>` on its line, or by its words matching a sub-issue's title. A box that maps to none is work no issue tracks: file it with `/dev-file-issue epic=<N>` (a title from the box, a body that quotes the box): it attaches the issue here and adds ` (#<sub>)` to that box's line. A box that is not work (a note, a question already answered in the maintainer's comments) goes to the `decider`: tick it with a one-line comment on the epic saying why, or file it.

### Step 3: Keep the epic branch and its PRs green

Look after the open sub-PRs as `/dev-pr` Step 7 (its steps 1-2: no verifier or auto-merge for a PR into the epic branch) and CLAUDE.md "Pull requests" say: a failing check is read, fixed test-first on its own branch, pushed; a review comment of the maintainer's is addressed, or recorded as a question when it needs the maintainer. When a sub-PR is green, mergeable and its review findings are dealt with, squash-merge it into the epic branch (`mcp__github__merge_pull_request`, `merge_method: squash`) and delete its branch; its sub-issue is now implemented.

**`main` moved:** `git fetch origin && git switch <epic branch> && git merge origin/main --no-edit`, resolve conflicts keeping both sides' intent as in `/dev-pr` Step 2, run the tests the conflicting files touch, push. Open sub-PRs then merge the epic branch in the same way (`git merge origin/<epic branch>`), so they stay mergeable. Do this when the epic's PR into `main` reports a conflict, and once before Step 8.

**A sub-PR closed without merging:** read why (the maintainer's comments on it). If the maintainer closed it on purpose, record that as a question and leave the sub-issue; otherwise it goes back to the queue and is resolved again from the epic branch's tip.

### Step 4: The next sub-issue

Pick the first open sub-issue, in GitHub's order, that has no PR yet and is not blocked:

- **Order**: a sub-issue that depends on one later in GitHub's order waits until that one is merged into the epic branch (pick the dependency first).
- **Blocked** means it needs a decision the `decider` could not take (record the question, mark it `blocked: question`), or it depends on a sub-issue that is `failed` or `blocked`. Go on with the next.
- **A sub-issue that is itself an epic** (it has sub-issues): work its sub-issues the same way, depth first.

If none is left to pick, go to Step 6.

Run `/dev-resolve <sub> epic=<N> base=<epic branch> target=<epic branch>` and follow it to the end: it makes the branch from the epic branch's tip, implements, validates, runs the review (CLAUDE.md "Review") and opens the PR into the epic branch, and returns without watching it; the loop's Step 3 watches it and merges it.

The issues its review filed (its report's Review line: only bugs a user would hit outside the change, CLAUDE.md "Review") went through `/dev-file-issue` as issues of their own, never into this epic: the epic's scope stays fixed while it is worked, so its queue does not grow. Name them in the final report.

If `/dev-resolve` ends in FAIL, record its diagnosis, comment it on the sub-issue, mark it `failed`, and go on: nothing of it is merged, and the next sub-issue builds on the same tip. Keep each sub-issue's review lines (what the reviewers found and how each ended) and, for a change to the app's screens, what a user sees: Step 8 uses them.

### Step 5: Tick the boxes

Tick a box (`- [ ]` → `- [x]`, adding ` — #<pr>`) only when its sub-issue's PR is merged into the epic branch, or with ` — not planned` when it was closed as not planned. Edit with `mcp__github__issue_write` (`method: update`), changing only those boxes: re-read the body first and keep every other character, since the maintainer may have edited it. Untick a box whose PR was closed unmerged.

### Step 6: Print the progress line, go round

One line per pass: `Epic #<N>: <done>/<total> sub-issues, <checked>/<total> boxes — next: <what>`. Then back to Step 1.

When nothing is left to start and sub-PRs still have checks running, wait for them instead of re-reading GitHub in a tight loop: one background command per PR (`gh pr checks <pr> --watch`), and go on when they finish.

---

## Step 7: When only the maintainer can move things on

Stop and wait only for a `blocked: question` (the `decider`'s CANNOT DECIDE): ask the questions together with AskUserQuestion, act on the answers and go back to the loop. A `failed` sub-issue, a PR the maintainer closed or a permission to wait for is asked about in the same message, but never stops work on the other sub-issues.

---

## Step 8: The epic's pull request and the final report

Reached when every sub-issue is merged into the epic branch, closed, `failed` or `blocked`, and every box is ticked or explained.

1. **Bring `main` in** (Step 3) and run the offline suite once on the epic branch (`./scripts/run-test.sh`, and `--app` when `app/` changed). Fix what fails test-first, on the epic branch.
2. **Show what changed.** When the epic's diff against `main` touches what a user sees (`app/src/renderer/`, `app/src/web/`, `app/src/preview/`, `docs/design/`, or the CLI's printed output):
   - **Screenshots**: render each changed screen in the preview (`npm run dev:preview` in `app/`, `?scene=…&state=…&theme=…`; the pages the design-reviewer used), with Playwright at `deviceScaleFactor: 2`, one image per screen and state that is new or changed, light and dark where the colours changed. Put a before shot (from `main`) beside it when something was changed, not added.
   - **GIF**: for a flow (several steps, something that moves), record it with the repo's recorders (`npm run record:gif`, `record:phone-gif`, a tape under `scripts/demo/` for the CLI) or a Playwright video turned into a GIF with `scripts/demo/app_gif.py`.
   - Write them to the scratchpad, never into the epic branch (nothing of them reaches `main`). Push them to the branch `epic-media/<N>` (made from `main` for the first push; only these files; `<N>/<name>.png`) and refer to them in the PR body as `![what it shows](https://github.com/synesenom/the-other-door/blob/epic-media/<N>/<N>/<name>.png?raw=true)`. When the session cannot push that branch (a fixed branch), send the files with `SendUserFile` and name them in the body instead.
   - Nothing a user sees: say "Nothing a user sees." and skip.
3. **Open the PR** `<epic branch>` → `main` with `/dev-pr epic=<N> final=true` (it uses the epic's commits as its own; `/dev-pr` Step 4's body, then):
   - `## Summary` first, for a person with no context: one plain sentence for the epic's goal, then one line per implemented sub-issue ("#12 — what a user can now do or what was fixed"), in a user's words, no code names.
   - `## What it looks like`: the images and GIFs from step 2.
   - `Closes #<sub>` for every implemented sub-issue and `Closes #<N>`, so merging closes them (GitHub only closes on a merge into `main`).
   Watch it as `/dev-pr` Step 7 says (checks, conflicts with `main`, the `verifier`, auto-merge).
4. **Report:**

```
Epic #<N> — <title>   Branch: <epic branch>   PR: #<pr> → main (checks: green|running|red, mergeable: yes|no, verify: success|pending|failure, merged: yes|no)
| Sub-issue | Title | Sub-PR (merged into the branch) | State |
|-----------|-------|----|-------|
| #12       | ...   | #40 | merged |
Sub-issues: <done>/<total> implemented   Filed for its boxes: #.., #..
Epic boxes: <checked>/<total> checked    Unchecked: <list, or none>
Filed outside the epic: #.., #..
Left for you: look at #<pr> (only when it carries `Needs the maintainer:`; the sub-PRs are the per-issue history); questions; or nothing
```

Then the summary in the PR's words (at most 10 short bullets, CLAUDE.md "Reporting back": what was added, each review finding and which way it went), the link to the PR, and the media (inline links, or the files sent).
