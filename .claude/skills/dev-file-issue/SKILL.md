---
name: dev-file-issue
description: File a GitHub issue for The other door and attach it as a sub-issue of an epic — an open epic whose goal it belongs to, or a new epic made for it. Every issue Claude files goes through this skill. Invoked with /dev-file-issue <title> [epic=<N>] [not_epic=<N>] (the body from the conversation).
---

You are filing one issue in The other door's tracker. **Repo constants**: `owner: synesenom`, `repo: the-other-door`.

No issue is left on its own: each one is a sub-issue of an epic. This is the only way Claude files an issue (a review finding, a box of an epic, a gap a skill or agent reports, a follow-up the user asks for).

Two optional arguments:

- `epic=<N>`: the issue is one of epic #N's own boxes (`/dev-epic` Step 2): attach it there, skip the choosing in Step 3.
- `not_epic=<N>`: never attach it to epic #N, the one a running `/dev-epic` is working on (`/dev-resolve` passes its `epic=` here), so a running epic's scope stays fixed.

---

## Step 1: Not a duplicate

`mcp__github__search_issues` with `repo:synesenom/the-other-door is:issue is:open` and the title's key words. If an open issue already asks for the same thing, do not file: comment on it what is new (`mcp__github__add_issue_comment`), give it an epic as in Step 3 if it has none, and report its number.

## Step 2: The issue

`mcp__github__issue_write`, `method: create`. The body stands on its own, read months later with no other context:

- the first line says where it came from (`Found by the gap review of #N`, `From epic #N's box`, `Asked by the user`);
- what is wrong or missing, with the evidence (files and lines, a command's output, a failing case);
- `## What`: what done looks like, test first (`Test first: …`).

Keep the response's `number` and `id`.

## Step 3: Its epic

The epics are the open issues that have sub-issues or whose title starts with `Epic:`:
`gh api graphql -f query='{repository(owner:"synesenom",name:"the-other-door"){issues(states:OPEN,first:100){nodes{number title subIssuesSummary{total}}}}}'`.
Read each one's body and sub-issues (`mcp__github__issue_read`, `method: get_sub_issues`) to know its goal. With `epic=`, that one; otherwise:

1. **An open epic whose goal the issue serves**: the one whose own text (its title, its opening paragraph, its boxes) the issue would finish, fix or test, not one merely about the same files, and never `not_epic`.
2. **Else a new epic.** `mcp__github__issue_write`, `method: create`, title `Epic: <the goal in a user's words>`, wide enough that the next issue of its kind belongs there too (`Epic: plain-words errors in the app`, not `Epic: #296`); body: one paragraph on the goal (what a user gets when it is done), then the box `- [ ] #<n> <title>`.
3. When unsure between them, the `decider` agent picks (CLAUDE.md "Decisions"), given the issue and the candidate epics' goals.

Attach it: `mcp__github__sub_issue_write`, `method: add`, `issue_number` the epic's number, `sub_issue_id` the new issue's `id` (not its number). For an existing epic, also give it its box (`mcp__github__issue_write`, `method: update`, re-reading the body first and changing nothing else): with `epic=`, add ` (#<n>)` to the box the issue came from; otherwise append `- [ ] #<n> <title>`.

Report one line: `#<n> <title> → epic #<e> (<existing | new>)`.
