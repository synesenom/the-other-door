---
name: dev-resolve
description: Fully resolve a GitHub issue — assess complexity, optionally research and plan, implement, then validate. Invoked with /dev-resolve <issue_number>.
---

You are the issue resolution orchestrator for The other door. The issue number is passed as the argument. Follow all steps in order without skipping.

**Decision policy**: make all decisions autonomously without pausing for user input. If anything is ambiguous, pick the simplest reasonable interpretation, document the choice, and proceed.

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
```

---

## Step 3: Validate

Determine the default branch: `git remote show origin | grep 'HEAD branch'`

Spawn the `issue-validator` agent with a prompt containing:

```
issue_number: <number>
issue_title: <title>
issue_body: <full body>
base_branch: <default branch>
```

Write the `## Validation Report` output to `thoughts/validate/<issue_number>.md`.

**If FAIL on first attempt**: automatically re-run the implementer (Step 2a or 2b-iii, whichever was used) with the validation report appended to the prompt as additional context:

```
validation_feedback: <full content of thoughts/validate/<issue_number>.md>
```

Then validate once more and write the new report to `thoughts/validate/<issue_number>.md`. Proceed to Step 4 regardless of the second result.

If the validator names a small gap it would still accept (a doc line, a comment), fix it yourself, commit it, and do not re-validate.

---

## Step 4: Open the pull request

On **PASS**, open the PR without asking: run `/dev-pr` and follow it to the end (branch name check, merge `main`, push, a body in its format built from the research, plan and validation reports, so the release notes can use it). A suite failure the validator showed also fails on a clean `main` goes in the body's test plan, said plainly.

On **FAIL** after two attempts, do not open a PR: the branch stays local, and Step 5 says why.

---

## Step 5: Final report

Summarise to the user:

```
Issue:       #<number> — <title>
Path:        Simple | Complex
Attempts:    1 | 2
Commit:      <short hash>
Validation:  PASS | FAIL
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
