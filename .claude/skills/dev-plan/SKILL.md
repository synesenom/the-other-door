---
name: dev-plan
description: Create a TDD implementation plan for a GitHub issue. Invoked with /dev-plan <issue_number>. Runs /dev-research first if no Research Report exists in the session context.
---

You are planning the implementation for a GitHub issue. The issue number is passed as the argument.

## Steps

1. **Load research** — check whether `thoughts/research/<issue_number>.md` exists.
   - If it exists, read it directly and skip to step 3.
   - If not, run `/dev-research <issue_number>` first (which will create the file), then read it.

2. **Spawn the `issue-planner` agent** with a prompt that includes:
   ```
   issue_number: <number>
   research_report: <full content of thoughts/research/<issue_number>.md>
   ```

3. **Save the output** — write the full `## Implementation Plan` and `## Risk Assessment` blocks to `thoughts/plan/<issue_number>.md`.

4. **Present the steps** to the user in this format:
   ```
   ## Plan: #<number> — <title>

   **Strategy**: <1–2 sentence summary of the overall approach>

   **Steps**:
   | # | File | What |
   |---|------|------|
   | 1 | `<file>` | [TEST] <what the test pins> |
   | 2 | `<file>` | [IMPL] <what the implementation does> |
   | … | … | … |

   **Risks**:
   - <risk> — <mitigation>
   - …

   Full plan saved to `thoughts/plan/<issue_number>.md`.
   ```
