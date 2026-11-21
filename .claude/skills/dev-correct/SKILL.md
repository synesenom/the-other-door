---
name: dev-correct
description: Turn the maintainer's repeated corrections of Claude into checks that enforce the rule. Run by hand, and by /dev-release before each release (with since=<previous tag>).
disable-model-invocation: true
---

Find mistakes the maintainer corrected more than once, and make the repository stop them: a check where a check is the natural fix, else a change to the architecture at the cause. A memory is only a reminder; an enforced rule cannot be forgotten.

**Argument**: optional `since=<ref>`: only evidence from that range (a release's use); turns from the ref's date on (`extract <dir> --since $(git log -1 --format=%cI <ref>)`).

## 1. Evidence

- Transcripts: `scripts/correct_evidence.py extract ~/.claude/projects/<this repo's folder> > $SCRATCH/turns.json` (private: scratchpad only, never committed). Spawn `correction-grouper` once (one Haiku call) with the turns, write its answer to `classes.json`, run `scripts/correct_evidence.py verify classes.json turns.json`. A quote that is not verbatim in a turn is dropped; only a class with `qualifies` (two or more distinct sessions) goes on.
- Git: `git log` for reverts, fix-ups and "drop"/"remove" commits; PR review comments (`gh api`), for the same mistakes.
- The feedback memories in `~/.claude/projects/*/memory/`: read only, never moved, edited or deleted.

## 2. The bar

A class needs at least 2 occurrences in different contexts; two corrections about the same case are one. Its wording is at the level of the cause. A rule that needs the instance named is a one-off: leave it out. At most 5 classes a sweep; the rest are named and left alone, as are behavioural rules (tone, how to report) that no check can hold.

## 3. The enforcer

For each class, one of:

- a `tests/**/test_*_guard_unit.py` whose failure message names the fix, shown failing on a named past commit (a worktree at `<sha>`, the test copied in) and passing on a held-out legitimate counter-case (not one that built the test);
- a change to the architecture or the agent prompts at the cause, so the mistake cannot be made (cite the past commit that made it).

One commit per class, its message naming the past commits it would have caught.

## 4. The table

Update the table "Rules and what enforces them" in `CLAUDE.md` (`rule | enforced by | since`): enforced rules only. Prune: a rule whose mistake can no longer happen, or that no correction touched since it was added, is dropped.

Report: the classes found, which got an enforcer (with the evidence it fails on the past commit), which were named and left alone.
