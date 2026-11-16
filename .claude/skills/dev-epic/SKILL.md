---
name: dev-epic
description: Churn through an epic issue in one run — resolve its sub-issues one after another, each in its own pull request branched from the previous one's, so the PRs build on each other and are kept green, file what is found on the way as new sub-issues, and tick the epic's checkboxes, until every sub-issue is implemented and every box is checked. Invoked with /dev-epic <epic_issue_number>.
---

You are working through an epic issue of The other door. The epic's number is the argument. **Repo constants**: `owner: synesenom`, `repo: the-other-door`, `base: main`.

**Decision policy**: decide alone; a question that is the maintainer's goes to the `decider` agent (CLAUDE.md "Decisions"), and only its CANNOT DECIDE goes to the user.

**Done** means both:

- every sub-issue of the epic (and of its sub-epics), including those added while working, is **implemented**: closed as completed, closed as not planned, or has an open pull request that closes it with every check green and no merge conflict;
- the epic's body has no unchecked `- [ ]` box.

Merging is the maintainer's: never merge, approve or enable auto-merge. Run the loop below until done. **Never stop before then**, except to ask a question the `decider` returned CANNOT DECIDE on (Step 7). Do not stop after one sub-issue to report or ask whether to go on. Something else only the maintainer can give (a merge, a permission the harness asks for, a hint for a `failed` sub-issue) blocks that one item, never the loop: ask for it in one line and go on with every other sub-issue. When the maintainer says something is merged or granted, re-read the epic at once and start what it unblocked, in the same turn.

**Never stop to report.** A sub-issue's PR opened, a step of `/dev-resolve` done, an agent returned, a decision taken, an issue filed: none ends the run. Go on to the next step or sub-issue in the same turn; the progress line (Step 6) is one line printed on the way, not a stopping point. While background agents or checks run, end the turn without a summary or a question and pick up the moment they finish. The only stops are Step 7 (only the maintainer can move things on), a CANNOT DECIDE, and a permission the harness must ask for. The report is Step 8, once, at the end.

State lives in `thoughts/epic/<N>.md` (the chain, in order; per sub-issue its branch, PR, state, notes; the open questions), so a later `/dev-epic <N>` picks up where this one stopped. Write it after every step that changes something.

**The chain.** The PRs build on each other: each sub-issue's branch starts from the previous sub-issue's branch, the first one from `main`. The chain is the ordered list of those branches whose PRs are still open; its **tip** is the last one (or `main` when the chain is empty, at the start or once everything is merged). Each PR still targets `main`, and `/dev-pr` describes only its own commits and says `Depends on #<previous pr>`. The maintainer merges them in chain order. Never rebase or force-push a chain branch: changes move up the chain by merges.

---

## The loop

Repeat Steps 1–6 until done; then Step 8.

### Step 1: Read the epic

Run in parallel:

- `mcp__github__issue_read` (`method: get`) on #`<N>`: title, body, labels, state.
- `mcp__github__issue_read` (`method: get_sub_issues`) on #`<N>`: every sub-issue, its number, title and state, in GitHub's order.
- Read `thoughts/epic/<N>.md` if it exists.

For each open sub-issue, find its pull request: `mcp__github__issue_read` (`method: get`) on it gives `closed_by_pull_requests`; when that is missing or empty, fall back to `gh api -X GET search/issues -f q='repo:synesenom/the-other-door is:pr is:open "Closes #<sub>"'` before treating it as PR-less. Read its checks (`mcp__github__pull_request_read`, `method: get_check_runs`) and whether it is mergeable (`method: get`).

Rebuild the chain from GitHub too, not only from the state file (it may be missing, in a new session): the open PRs that say `Part of #<N>`, ordered by their `Depends on #` lines, the first one with none.

Read GitHub again on every pass: the counts are never remembered. If the epic is closed, go to Step 8.

### Step 2: Every box has a sub-issue

Read the body's checkboxes. Each unchecked box must map to a sub-issue: by a `#<sub>` on its line, or by its words matching a sub-issue's title. A box that maps to none is work no issue tracks: file it (`mcp__github__issue_write`, `method: create`, a title from the box, a body that quotes the box and links the epic), attach it (`mcp__github__sub_issue_write`, `method: add`, `sub_issue_id` the new issue's `id`, not its number), and add ` (#<sub>)` to the box's line in the epic body. A box that is not work (a note, a question already answered in the comments) goes to the `decider`: tick it with a one-line comment on the epic saying why, or file it.

### Step 3: Keep the chain green

Look after the chain's PRs as `/dev-pr` Step 7 and CLAUDE.md "Pull requests" say: a failing check is read, fixed test-first on its own branch, pushed; a review comment is addressed, or recorded as a question when it needs the maintainer. A conflict with `main`, or `main` moving, is never fixed in the middle: merge `origin/main` into the bottom branch, then carry it up. PR events that arrive while you work are handled here on the next pass.

**Carry every change up the chain.** After pushing to a chain branch, merge it into the next one, push, and so on to the tip, running the tests the merge touches at each step: `git fetch origin && git switch <next> && git merge origin/<prev> --no-edit && git push`. A conflict is resolved keeping both sides' intent, as in `/dev-pr` Step 2.

**A chain PR merged:** it and every chain PR below it are now in `main`. Drop them from the chain; a PR below it that is still open is included already: close it with a comment naming the merged PR, and close its sub-issue as completed. Then merge `origin/main` into the new bottom branch, update its body's `Depends on` (`mcp__github__update_pull_request`; none when it is now first), and carry it up.

**A chain PR closed without merging:** the branches above still hold its commits. Read why (its comments). Revert its own commits on the next branch (`git revert --no-edit origin/<branch below>..origin/<closed branch>`; `origin/main` when it was the bottom), carry that up, drop it from the chain and point the next PR's `Depends on` at the PR below it. If the maintainer closed it on purpose, record that as a question and leave the sub-issue; otherwise it goes back to the queue and is resolved again on the tip.

### Step 4: The next sub-issue

Pick the first open sub-issue, in GitHub's order, that has no PR yet and is not blocked:

- **Order**: a sub-issue that depends on one later in GitHub's order waits until that one is in the chain (pick the dependency first): the chain only builds upward.
- **Blocked** means it needs a decision the `decider` could not take (record the question, mark it `blocked: question`), or it depends on a sub-issue that is `failed` or `blocked`. Go on with the next.
- **A sub-issue that is itself an epic** (it has sub-issues): work its sub-issues the same way, depth first.

If none is left to pick, go to Step 6.

A branch the session's own instructions fix (a cloud session's single branch) wins over the one `/dev-resolve` would make: then the epic's PRs go out one at a time, the next only once the last is merged, and Step 7 applies while waiting.

Run `/dev-resolve <sub> epic=<N> base=<tip>` (`base=main` when the chain is empty; in the fixed-branch case above, no `base`: it stays on that branch) and follow it to the end: it makes the branch from the tip, implements, validates, runs the review (CLAUDE.md "Review") and opens the PR, and returns without watching it; the loop's Step 3 watches it.

Afterwards, sort the issues its review filed (its report's Review line): one **within the epic's goal** is attached to the epic as a new sub-issue (`mcp__github__sub_issue_write`, `method: add`, its `id`), and so joins the queue; one outside it stays on its own and is named in the final report. Attach only what the epic's own text asks for or makes necessary, so the queue does not grow without end.

On a PR, its branch becomes the chain's new tip. If `/dev-resolve` ends in FAIL, record its diagnosis, comment it on the sub-issue, mark it `failed`, and go on: its branch does not join the chain, and the next sub-issue builds on the same tip.

### Step 5: Tick the boxes

Tick a box (`- [ ]` → `- [x]`, adding ` — #<pr>`) only when its sub-issue is implemented, or with ` — not planned` when it was closed as not planned. Edit with `mcp__github__issue_write` (`method: update`), changing only those boxes: re-read the body first and keep every other character, since the maintainer may have edited it. Untick a box whose PR went red or was closed unmerged.

### Step 6: Print the progress line, go round

One line per pass: `Epic #<N>: <done>/<total> sub-issues, <checked>/<total> boxes — next: <what>`. Then back to Step 1.

When nothing is left to start and PRs still have checks running, wait for them instead of re-reading GitHub in a tight loop: one background command per PR (`gh pr checks <pr> --watch`), and go on when they finish.

---

## Step 7: When only the maintainer can move things on

Stop and wait only for a `blocked: question` (the `decider`'s CANNOT DECIDE): ask the questions together with AskUserQuestion, act on the answers and go back to the loop. A `failed` sub-issue, a PR the maintainer closed or a permission to wait for is asked about in the same message, but never stops work on the other sub-issues. Open PRs waiting for a merge count as implemented (see **Done**); when they are all that is left, the epic is done: report (Step 8).

---

## Step 8: Final report

```
Epic #<N> — <title>
| Sub-issue | Title | PR | Checks | Mergeable | State |
|-----------|-------|----|--------|-----------|-------|
| #12       | ...   | #40 | green | yes | PR open (chain 1) |
|   ↳ #15   | ...   | #41 | green | yes | PR open (chain 2) |
...
Sub-issues: <done>/<total> implemented   Added on the way: #.., #..
Epic boxes: <checked>/<total> checked    Unchecked: <list, or none>
Filed outside the epic: #.., #..
Left for you: <PRs to merge, in chain order, bottom first; questions; or nothing>
```

Then at most 10 short bullets (CLAUDE.md "Reporting back"): what was done, each review finding and which way it went.
