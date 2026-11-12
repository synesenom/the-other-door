---
name: dev-research
description: Research a GitHub issue and produce a codebase analysis report. Invoked with /dev-research <issue_number>.
---

You are researching a GitHub issue to understand what needs to change in the codebase. The issue number is passed as the argument.

The `issue-researcher` agent has `WebSearch`/`WebFetch` and uses them when the issue depends on knowledge outside the repo (third-party site/API behaviour, library or tooling semantics, dependency error messages, specs). It records every source under the report's **External research** section and does not web-search anything answerable from the codebase alone.

## Steps

1. **Fetch the issue** — use `mcp__github__issue_read` with:
   - `owner`: `synesenom`
   - `repo`: `the-other-door`
   - `issue_number`: the number from the argument

2. **Spawn the `issue-researcher` agent** with a prompt that includes:
   ```
   issue_number: <number>
   issue_title: <title from fetched issue>
   issue_body: <body from fetched issue>
   issue_labels: <comma-separated label names, or "none">
   ```

3. **Save the output** — write the full `## Research Report` block to `thoughts/research/<issue_number>.md`.

4. **Present key findings** to the user in this format:
   ```
   ## Research: #<number> — <title>

   **Problem**: <1–2 sentence summary of what is broken or missing>

   **Affected files**:
   - `<file>` — <what needs to change>
   - …

   **Key constraints**:
   - <constraint or risk worth flagging>
   - …

   **Suggested approach**: <1–2 sentence summary>

   Full report saved to `thoughts/research/<issue_number>.md`.
   ```
