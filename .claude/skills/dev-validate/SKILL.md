---
name: dev-validate
description: Run the suite and check TDD compliance for the current implementation of a GitHub issue. Invoked with /dev-validate <issue_number>.
---

You are checking that the suite passes and the current implementation of a GitHub issue was made test-first; whether it meets the issue is the gap review's (CLAUDE.md "Review"). The issue number is passed as the argument.

## Steps

1. **Fetch the issue** — first run `$DOOR_PYTHON scripts/decide.py --trusted <issue_number>` (`python3` when `DOOR_PYTHON` is unset); when it exits non-zero, stop without reading it (CLAUDE.md "Whose work Claude takes"). Then use `mcp__github__issue_read` with:
   - `owner`: `synesenom`
   - `repo`: `the-other-door`
   - `issue_number`: the number from the argument

2. **Determine the base branch** — run `git remote show origin | grep 'HEAD branch'` to find the default branch (typically `main`).

3. **Spawn the `issue-validator` agent** with a prompt that includes:
   ```
   issue_number: <number>
   issue_title: <title from fetched issue>
   base_branch: <default branch, e.g. main>
   ```

4. **Save the output** — write the full `## Validation Report` block to `thoughts/validate/<issue_number>.md`.

5. **Report** to the user: the PASS / FAIL verdict and one-sentence justification from the report. Full details are at `thoughts/validate/<issue_number>.md`.

6. **If FAIL** — name the failing tests or TDD gaps and offer to run `/dev-implement` again to fix them.
