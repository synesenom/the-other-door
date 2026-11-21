---
name: dev-plan-epic
description: Plan a whole epic before any of it is built — architects research the feature and the codebase and propose competing plans, two critics break them and argue the pros and cons, and the surviving plan, the smallest that reaches the goal and using a model wherever the work is reading meaning, is written down and (once the maintainer agrees) filed as an epic with its sub-issues. Invoked with /dev-plan-epic <goal in words | existing epic number>.
---

You are planning an epic for The other door. The argument is the goal in the maintainer's words, or the number of an existing epic or issue whose goal is to be planned (first run `$DOOR_PYTHON scripts/decide.py --trusted <number>` (`python3` when `DOOR_PYTHON` is unset), and stop without reading it when it exits non-zero, CLAUDE.md "Whose work Claude takes"; then read it with `mcp__github__issue_read`, `method: get`, and its sub-issues with `get_sub_issues`; an epic that already has sub-issues is *re-planned*: the plan says what to keep, change, drop and add). **Repo constants**: `owner: synesenom`, `repo: the-other-door`.

**Why this exists.** An epic planned in one pass tends to start from a programmatic detector, then grow issue by issue as real inputs show the idea was flawed (reading a CV's sections and headings with rules, when one cheap model call does it). This skill makes the plan fight before it costs anything. Two rules bind every step:

1. **A model understands, code verifies.** Reading free-form input and deciding what it means is a cheap model call (`claude_cli.ask()`, a JSON schema, Haiku); code stores, shows and checks. A plan that interprets text with heuristics has to defend that against a model call, with numbers.
2. **The smallest change that reaches the goal.** Fewest sub-issues, files, lines and new concepts; reuse what exists; no option, fallback or hook nothing needs; delete what becomes dead.

**Decision policy**: decide alone; what is the maintainer's goes to the `decider` agent (CLAUDE.md "Decisions"), and only its CANNOT DECIDE is asked. Filing is the one confirmation (Step 7).

State: `thoughts/epic-plan/<slug>.md` (`<slug>` two to five words of the goal), written after Step 5 and again after each later step. Never stop between steps to report.

---

## Step 1: The goal

State the goal as what a user gets when the epic is done, in one sentence, and the audience (a person using the app, the CLI, Claude Code, or the developer). If the argument is vague, take the simplest reading and note it as an assumption; do not ask. Read `CLAUDE.md` and `docs/architecture.md`, and find the existing epics and open issues that overlap (`mcp__github__list_issues`, `gh api -X GET search/issues`): overlap with an open epic is a reason to extend it, not to plan a second.

## Step 2: Two architects, in parallel

Spawn the `epic-architect` agent twice in one message, each with the goal, the assumptions, the overlapping issues and one lens:

- `outcome-first`
- `codebase-first`

They research the feature and the code independently and each returns an `## Epic Plan`. Save both plans in the state file. If a plan says its riskiest assumption can be tested in minutes with a command (not a build), run that test now yourself and give the result to the critics.

## Step 3: Two critics, in parallel

Spawn `epic-critic` twice in one message, round `critique`, each given the goal and **both** plans verbatim:

- stance `scope`
- stance `approach`

## Step 4: They answer each other

Spawn both again, round `rebuttal`, each given both plans and **the other critic's** `## Critique`. They return concede / hold / merge per point and the trade-offs that remain.

## Step 5: The final plan

Spawn one `epic-architect` with lens `final` and `model: fable` (the one crucial call: it is the plan everything else is built on; every other agent here runs on Opus), given the goal, both plans, both critiques and both rebuttals. It returns the one `## Epic Plan` that survives, with the disputed points listed, each with both sides.

Take every disputed point the maintainer would otherwise decide to the `decider` (the question, the two sides, the context); fold its decisions into the plan with a one-line reason each. A decision it cannot take stays a question in the plan.

## Step 6: The gate

Run the checks yourself, then spawn both critics once more, round `gate`, with the final plan. Yourself:

- every sub-issue is needed for a check in "Done when" (no orphan); every check is met by some sub-issue;
- every check is testable as far as it can be: each says what to run and what it shows, so the `verifier` can run it (a command, a script on sample input, the test-world app); one only the maintainer can run (a clean-machine install, a real phone) ends with `(by the maintainer)` and waits for them;
- every step that interprets input is a model call, or its code has a real reason (determinism, cost at the plan's usage, offline) with a number;
- the riskiest assumption has a spike first, with a numeric go/no-go, or "None" with a reason;
- no option, key, flag, fallback or "for later" hook appears that no check needs; no sub-issue is only preparation for another;
- "Not doing" lists what a reader would expect and is not there; the size line is true.

If a critic answers `BLOCK`, or a check fails, send the final architect the problems and go round Step 5 again. At most two rounds; a block that survives them goes to the `decider`, and CANNOT DECIDE goes to the maintainer with the plan.

## Step 7: Show it, then file it

Write the plan to `thoughts/epic-plan/<slug>.md` and show the maintainer, in plain words and at most 200 words (CLAUDE.md "Reporting back"): the goal; the shape (sub-issues, files, lines, new concepts); where a model is used and where code is; the riskiest assumption and its spike; what the critics changed from the first plans and what they could not agree on; the "Not doing" list; the path to the file.

Then ask once (AskUserQuestion): file it as an epic with its sub-issues, or stop with the plan on disk. This is outward-facing, so it is asked. On yes:

1. `mcp__github__issue_write`, `method: create`: title `Epic: <the goal in a user's words>`; body: the goal paragraph, `**Done when**` with its checks, `## Plan` with the plan's **Riskiest assumption** and **Not doing**, the line `Planned by /dev-plan-epic` (the mark `/dev-epic` requires; the plan file is not in the repo, so the body carries everything `/dev-epic` needs: goal, done-when, riskiest assumption with its go/no-go and its "if no-go", and not-doing), and one box per sub-issue, `- [ ] <title>`, in order. For a re-plan, edit the existing epic's body the same way (re-read it first; keep every other character) and close with `state_reason: not_planned` the sub-issues the plan drops, with a comment naming the plan.
2. For each sub-issue in order: `/dev-file-issue <title> epic=<N>`, the body from the plan (what changes and why, the files, the first failing test, done when, and which sub-issue it follows). It attaches the issue and adds ` (#<n>)` to its box.
3. Report one line: `Epic #<N> with <k> sub-issues; run it with /dev-epic <N>.`

`/dev-epic` then works the epic in the order the plan gives; the spike's go/no-go is its first sub-issue's done, and on a no-go it stops and says so (the plan's "if no-go" line), rather than building on.
