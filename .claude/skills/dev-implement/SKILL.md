---
name: dev-implement
description: Implement code changes to resolve a GitHub issue following TDD. Invoked with /dev-implement <issue_number>. Runs /dev-research and /dev-plan first if their outputs are not already saved.
---

You are implementing the code changes for a GitHub issue. The issue number is passed as the argument.

## Steps

1. **Load context** — check for saved outputs:
   - Research: `thoughts/research/<issue_number>.md`
   - Plan: `thoughts/plan/<issue_number>.md`

2. **Fill gaps** — for any missing file, generate it silently (do not present the report or plan content to the user):
   - No research file: run `/dev-research <issue_number>`.
   - No plan file: run `/dev-plan <issue_number>`.

3. **Spawn the `issue-implementer` agent** with a prompt that includes:
   ```
   issue_number: <number>
   research_report: <full content of thoughts/research/<issue_number>.md, or "none">
   plan: <full content of thoughts/plan/<issue_number>.md, or "none">
   ```

4. **Report** to the user: files changed, tests added, and commit hash.
