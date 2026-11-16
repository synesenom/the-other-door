---
name: dev-resolve
description: Fully resolve a GitHub issue — assess complexity, optionally research and plan, implement, validate, review, then open the pull request. Invoked with /dev-resolve <issue_number> [base=<branch>] [epic=<number>].
---

You are the issue resolution orchestrator for The other door. The issue number is passed as the argument. Follow all steps in order without skipping.

Two optional arguments, which `/dev-epic` passes for each sub-issue:

- `base=<branch>`: the branch the change builds on (in an epic, the previous sub-issue's); default the default branch. The issue's branch starts from it (`issue-implementer`'s step 0, given `base_branch`).
- `epic=<number>`: the epic the issue belongs to; `/dev-pr` says what changes.

**Decision policy**: make all decisions autonomously without pausing for user input. If anything is ambiguous, pick the simplest reasonable interpretation, document the choice, and proceed.

**Never stop to report.** The run ends only at Step 6 (or, inside `/dev-epic`, by handing back to the epic's loop, which goes straight on). Finishing a step, an agent returning, a decision taken or an issue filed is not a reason to end the turn with a summary: start the next step in the same turn. While a background agent runs, end the turn only with no question and no summary, and resume the next step as soon as it returns. The only stop to wait for the user is a CANNOT DECIDE. A permission the harness must ask for is asked in one line while the rest of the run goes on; FAIL after two attempts ends this issue's run (Step 6), never the epic's loop.

---

## Step 1: Fetch and assess the issue

Use `mcp__github__issue_read` (`owner: synesenom`, `repo: the-other-door`) to fetch the issue. Read the title, body, and labels in full.

**Assess complexity** — tally the signals below:

| Signal | Score |
|--------|-------|
| Issue mentions a specific file or function by name | −1 |
| Issue includes exact error message or failing test | −1 |
| Issue title contains: typo / doc / rename / formatting | −2 |
| Issue is a new feature or "add support for" request | +2 |
| Issue requires changes to multiple files or scrapers | +1 |
| Issue involves `src/door/core/models.py`, `src/door/scrapers/__init__.py`, or `browser.py` | +1 |
| Issue requirements are ambiguous or open-ended | +1 |
| Issue has the label `enhancement` or `feature` | +1 |

- **Score ≤ 0 → Simple path** (Step 2a)
- **Score > 0 → Complex path** (Step 2b)

Tell the user: the issue title, score, and path chosen.

---

## Step 2a: Simple path

Spawn the `issue-implementer` agent with a prompt containing:

```
issue_number: <number>
issue_title: <title>
issue_body: <full body>
research_report: none
plan: none
base_branch: <base, when given>
```

Go to Step 3.

---

## Step 2b: Complex path

### 2b-i Research

Check whether `thoughts/research/<issue_number>.md` already exists — if so, read it and skip spawning the researcher.

Otherwise, spawn the `issue-researcher` agent with a prompt containing:

```
issue_number: <number>
issue_title: <title>
issue_body: <full body>
issue_labels: <labels or "none">
```

Write the `## Research Report` output to `thoughts/research/<issue_number>.md`.

### 2b-ii Plan

Check whether `thoughts/plan/<issue_number>.md` already exists — if so, read it and skip spawning the planner.

Otherwise, spawn the `issue-planner` agent with a prompt containing:

```
issue_number: <number>
research_report: <full content of thoughts/research/<issue_number>.md>
```

Write the `## Implementation Plan` and `## Risk Assessment` output to `thoughts/plan/<issue_number>.md`.

Proceed immediately to implementation.

### 2b-iii Implement

Spawn the `issue-implementer` agent with a prompt containing:

```
issue_number: <number>
issue_title: <title>
issue_body: <full body>
research_report: <full content of thoughts/research/<issue_number>.md>
plan: <full content of thoughts/plan/<issue_number>.md>
base_branch: <base, when given>
```

---

## Step 3: Validate

The base branch is `base` when given, else the default branch (`git remote show origin | grep 'HEAD branch'`).

Spawn the `issue-validator` agent with a prompt containing:

```
issue_number: <number>
issue_title: <title>
base_branch: <base branch>
```

Write the `## Validation Report` output to `thoughts/validate/<issue_number>.md`.

**If FAIL on first attempt**: automatically re-run the implementer (Step 2a or 2b-iii, whichever was used) with the validation report appended to the prompt as additional context:

```
validation_feedback: <full content of thoughts/validate/<issue_number>.md>
```

Then validate once more and write the new report to `thoughts/validate/<issue_number>.md`. Proceed to Step 4 regardless of the second result.

---

## Step 4: Review

On **PASS** only (on FAIL go to Step 6). Run the reviewers CLAUDE.md "Review" names, in its order, with `base_branch: <base branch>` and the issue as the goal. Fix each finding on the branch (test-first, then run the tests it touches) or file it as an issue that stands alone and names this one. Keep the list of findings and how each ended (fixed, filed `#N`, not real) for the PR body and Step 6.

---

## Step 5: Open the pull request

On **PASS**, open the PR without asking: run `/dev-pr` and follow it (branch name check, merge `main`, push, a body in its format built from the research, plan and validation reports and the review, so the release notes can use it). The body's Changes say each review finding and how it ended. A suite failure the validator showed also fails on a clean `main` goes in the body's test plan, said plainly. Pass on `base` and `epic` (`/dev-pr base=<base> epic=<epic>`), when given.

On **FAIL** after two attempts, do not open a PR: the branch stays local, and Step 6 says why.

---

## Step 6: Final report

Summarise to the user:

```
Issue:       #<number> — <title>
Path:        Simple | Complex
Attempts:    1 | 2
Commit:      <short hash>
Validation:  PASS | FAIL
Review:      <n> fixed, <n> filed (#.., #..), <n> not real
PR:          #<number> <url> | not opened (FAIL)
```

Then add a **What was implemented** section in plain prose (3–6 sentences). Cover:
- What new code was introduced (new files, classes, functions) and what it does
- How existing code was changed and why (what problem it solves)
- Any notable design decisions or trade-offs made during implementation

Then add:
```
Changed:     <list of files changed>
Tests added: <list of new test functions/files>
```

If still FAIL after two attempts: include a one-paragraph diagnosis of what is missing and why — the user can then decide how to proceed.
