---
name: dev-file-issue
description: File a GitHub issue for The other door and attach it as a sub-issue of an epic — an open epic whose goal it belongs to, or a new epic made for it. Every issue Claude files goes through this skill. Invoked with /dev-file-issue <title> (the body from the conversation, or after the title).
---

You are filing one issue in The other door's tracker. **Repo constants**: `owner: synesenom`, `repo: the-other-door`.

No issue is left on its own: each one is a sub-issue of an epic. This is the only way Claude files an issue (a review finding, a box of an epic, a gap a skill or agent reports, a follow-up the user asks for).

---

## Step 1: Not a duplicate

`mcp__github__search_issues` with `repo:synesenom/the-other-door is:issue is:open` and the title's key words. If an open issue already asks for the same thing, do not file: comment on it what is new (`mcp__github__add_issue_comment`), and return its number. Its epic is checked as in Step 3 (an open issue with no parent gets one).

## Step 2: The issue

`mcp__github__issue_write`, `method: create`. The body stands on its own, read months later with no other context:

- the first line says where it came from (`Found by the gap review of #N`, `From epic #N's box`, `Asked by the user`);
- what is wrong or missing, with the evidence (files and lines, a command's output, a failing case);
- `## What`: what done looks like, test first (`Test first: …`).

Keep the response's `number` and `id`.

## Step 3: Its epic

An epic is an open issue whose title starts with `Epic:` (`mcp__github__search_issues`, `repo:synesenom/the-other-door is:issue is:open "Epic:" in:title`); read each one's body and its sub-issues (`mcp__github__issue_read`, `method: get_sub_issues`) to know its goal.

1. **An open epic whose goal the issue serves**: the one whose own text (its title, its opening paragraph, its boxes) the issue would finish, fix or test. Not an epic merely about the same files. Never the epic a running `/dev-epic` is working, unless the issue is one of that epic's own boxes (Step 2 of `/dev-epic`): a running epic's scope stays fixed, and a review finding of one of its sub-issues goes to another epic.
2. **Else a new epic.** `mcp__github__issue_write`, `method: create`, title `Epic: <the goal in a user's words>`, body: one paragraph on the goal (what a user gets when it is done, and why it is one piece of work), then one box per sub-issue, `- [ ] #<n> <title>`. Name the goal wide enough that the next issue of its kind belongs there too (`Epic: plain-words errors in the app`, not `Epic: #296`).
3. When unsure between an existing epic and a new one, the `decider` agent picks (CLAUDE.md "Decisions"), given the issue and the candidate epics' goals.

Attach it: `mcp__github__sub_issue_write`, `method: add`, `issue_number` the epic's number, `sub_issue_id` the new issue's `id` (not its number). Then add its box to the epic's body (`mcp__github__issue_write`, `method: update`, re-reading the body first and changing nothing else): `- [ ] #<n> <title>`.

## Step 4: Report

One line: `#<n> <title> → epic #<e> (<existing | new>)`. The caller names `#<n>` where it records the finding (the PR body's Review, the final report).
