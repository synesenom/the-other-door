---
name: dev-file-issue
description: File a GitHub issue for The other door after a duplicate check, as a sub-issue of an epic only when it is one of that epic's own boxes. Every issue Claude files goes through this skill. Invoked with /dev-file-issue <title> [epic=<N>] (the body from the conversation).
---

You are filing one issue in The other door's tracker. **Repo constants**: `owner: synesenom`, `repo: the-other-door`.

This is the only way Claude files an issue (a review finding, a box of an epic, a gap a skill or agent reports, a follow-up the user asks for). An issue stands on its own; it goes under an epic only when it is one of that epic's own boxes.

One optional argument:

- `epic=<N>`: the issue is one of epic #N's own boxes (`/dev-plan-epic`, `/dev-epic` Step 2): attach it there (Step 3).

---

## Step 1: Not a duplicate

`mcp__github__search_issues` with `repo:synesenom/the-other-door is:issue is:open` and the title's key words. If an open issue already asks for the same thing, do not file: comment on it what is new (`mcp__github__add_issue_comment`) and report its number.

## Step 2: The issue

`mcp__github__issue_write`, `method: create`. The body stands on its own, read months later with no other context:

- the first line says where it came from (`Found by the gap review of #N`, `From epic #N's box`, `Asked by the user`);
- what is wrong or missing, with the evidence (files and lines, a command's output, a failing case);
- `## What`: what done looks like, test first (`Test first: …`).

Keep the response's `number` and `id`.

## Step 3: Its epic, only with `epic=`

Attach it: `mcp__github__sub_issue_write`, `method: add`, `issue_number` the epic's number, `sub_issue_id` the new issue's `id` (not its number). Then add ` (#<n>)` to the box the issue came from (`mcp__github__issue_write`, `method: update`, re-reading the body first and changing nothing else).

Report one line: `#<n> <title>` (with `→ epic #<e>` when attached).
