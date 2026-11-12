---
name: upskill
description: Analyse skill gaps between the candidate profile and target role(s), then emit a prioritized, WebSearch-cited learning plan to upskill/report-YYYY-MM-DD.md.
tools: [Read, mcp__door__doctor, mcp__door__skill_gaps]
---

You are producing a skill-gap report for the candidate. The analysis, the searching and
the writing are the `skill_gaps` tool's (the same one call as `cv gaps` in a
shell); your job is to pass it the right targets and summarise the result. Follow these
steps.

## Step 1 — Check the profile

Call `mcp__door__doctor` and look at its `profile` check. If its `detail` says the
config is not found (no profile yet), stop with: "profile/config.json not found — run
/onboard first." If its `status` is anything else but `ok`, show its `detail` (every
config error) and stop: every command would reject this config too.

## Step 2 — Work out the targets

From the argument passed to this skill:

- A role name (e.g. `/upskill "Senior Accountant"`) → `targets: ["Senior Accountant"]`.
- One or more jobs, named by company or title words (e.g. `/upskill trustpilot`) →
  `jobs: ["trustpilot"]`; the tool resolves them, and returns `candidates` when several
  jobs match: ask which with AskUserQuestion, then pass that `job_id`.
- `top N` (e.g. `/upskill top 5`) → `top: 5`.

Refer to postings by title and company when talking to the user; never ask them for an id or
a file path. If no argument is provided, ask: "Which role or matches should I analyse?
Give a role name, a job (e.g. 'the Trustpilot one'), or 'top 5'." Only proceed once you
have at least one target.

## Step 3 — Run the analysis

Call `mcp__door__skill_gaps` with `targets`, `jobs` and/or `top`. It takes minutes: one
`claude -p` call does a hard-skill diff (Pass 1), synthesises broader gaps (Pass 2), finds
real resources with WebSearch (never invented — a gap with none is listed under "Skipped
gaps") and writes `upskill/report-YYYY-MM-DD.md`. If it returns an `error`, show it and
stop.

## Step 4 — Report

Read the report at `report_path` and summarise it: the targets analysed (`targets`), the
top three gaps of the prioritised plan with one resource each, and what was skipped. End
with: "Upskill plan written to <report_path> — <plan_items> gap(s) with a plan."
