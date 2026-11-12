---
name: dev-validate
description: Validate that the current implementation resolves a GitHub issue. Invoked with /dev-validate <issue_number>.
---

You are validating whether the current implementation resolves a GitHub issue. The issue number is passed as the argument.

## Steps

1. **Fetch the issue** — use `mcp__github__issue_read` with:
   - `owner`: `synesenom`
   - `repo`: `the-other-door`
   - `issue_number`: the number from the argument

2. **Determine the base branch** — run `git remote show origin | grep 'HEAD branch'` to find the default branch (typically `main`).

3. **Spawn the `issue-validator` agent** with a prompt that includes:
   ```
   issue_number: <number>
   issue_title: <title from fetched issue>
   issue_body: <body from fetched issue>
   base_branch: <default branch, e.g. main>
   ```

4. **Save the output** — write the full `## Validation Report` block to `thoughts/validate/<issue_number>.md`.

5. **Report** to the user: the PASS / FAIL verdict and one-sentence justification from the report. Full details are at `thoughts/validate/<issue_number>.md`.

6. **If FAIL** — describe what is still missing and offer to run `/dev-implement` again to address the gaps.
