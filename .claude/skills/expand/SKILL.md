---
name: expand
description: Enrich profile/cv.md from public URLs — fetches, proposes, and writes only after user confirmation.
tools: [AskUserQuestion, mcp__door__doctor, mcp__door__enrich]
---

You are enriching the candidate's CV with skills and achievements evidenced on their
public pages. The work is the `enrich` tool's (the same two calls as `cv enrich` in a
shell); your job is to show its proposals and ask which to keep. Follow these steps.

1. **Check the profile** — call `mcp__door__doctor` and look at its `profile` check. If
   its `detail` says the config is not found (no profile yet), stop with:
   "profile/config.json not found — run /onboard first." If its `status` is anything else
   but `ok`, show its `detail` (every config error) and stop.

2. **Propose** — call `mcp__door__enrich` with `urls` = the URLs passed to this skill
   (e.g. `/expand https://janedoe.example.com`), or no `urls` to read the profile's
   `enrich_sources`. It fetches the pages with one `claude -p` call and returns numbered
   `proposals` (section, text, source) that are evidenced on the pages and not already in
   the CV; nothing is written. If it returns an `error` naming `enrich_sources`, stop with:
   "No URLs provided. Pass URLs as arguments (e.g. `/expand https://janedoe.example.com`) or add
   them to `enrich_sources` in profile/config.json." Show any other `error` and stop.

3. **Show** — for each URL in `unreachable`, say "Could not fetch <url> — skipping." If
   `outcome` is `nothing_new`, report "Nothing new found across all sources." and stop.
   Otherwise list the proposals by number, each with its section, text and source.

4. **Ask** — which to add, with `AskUserQuestion`: one `multiSelect` question per group of
   up to 4 proposals (the number and text in the label, the section and source in the
   description), plus "All of them" and "None" where they fit. The box hides the text
   above it, so the proposals go inside the options.

5. **Apply** — nothing chosen: report "No changes made." and stop. Otherwise call
   `mcp__door__enrich` again with `apply` = the chosen numbers (or `all=True`). It inserts
   each bullet under its `##` section (a new section at the end when there is none) and
   keeps the previous CV as `cv.md.bak`.

6. **Report** — list every addition from `added` and remind the user: "Review the changes
   in profile/cv.md before your next run."
