#!/usr/bin/env python3
"""Whether a PR's head has what the verifier needs to pass it: `python scripts/decide.py <pr> --checks <file.json>`.

`python scripts/decide.py --open` lists the user's open PRs that need something (the
session-start hook): a conflict, a failed or missing check, the `verify` status, or, before the
verifier has spoken, the body's `Needs the maintainer:` lines, read as the gate reads them.

`<pr> --checks <file.json>` is the verifier's verdict, computed here and not
written by it: the file lists its checks `{"goal", "saw", "matches_goal", "ran"}` (the goal in the
issue's own words, verbatim); a check that ran and misses its goal is a failure, one not run, or a
Done-when sentence of the issue with no check, is pending, else the gate below decides. Prints {"state", "description", "reasons", "sha"}.
`--checks <file> --issue <file>` is the same offline (no gh; the gate counts as ok), for a spike.
`--trusted <n>` says whether Claude may take work from issue or PR #n, read before its text is:
{"trusted": opened by the repo owner, "author", "strangers": its sub-issues opened by anyone else};
exits 0 only when trusted, and a gh failure is not trusted.
A PR, or an issue it closes, opened by anyone but the repo owner needs the maintainer; the guard
sees only closing references (`Closes #N`), which `/dev-pr` writes for every issue. A PR with no
closing issue (a direct request) has its goals read from its own body.

Exits 0 on success, 1 otherwise, 2 for a missing `--checks`. Reads the PR and its head's check
runs through `gh`; the `verify` check (the verifier's own status) is left out. A PR that changes
what a user sees is never ok: the maintainer looks at it.
"""

import json
import re
import subprocess
import sys

REPO = "synesenom/the-other-door"
GREEN = {"success", "skipped", "neutral"}
VISIBLE = ("app/src/renderer/", "app/src/web/", "app/src/preview/", "docs/design/")
OWNER = "synesenom"
MAINTAINER = "Needs the maintainer: look at it"


def decide(checks, body, files, head, author=OWNER, issues=()):
    """Return (ok, reasons) for a head's check runs, the PR body, the changed file paths, the PR's
    author and the closing issues as (number, author)."""
    reasons = []
    if author != OWNER:
        reasons.append(f"Needs the maintainer: opened by {author}")
    reasons += [f"Needs the maintainer: issue #{n} opened by {who}" for n, who in issues if who != OWNER]
    if not checks:
        reasons.append("no checks yet")
    for c in checks:
        if c["head_sha"] != head:
            reasons.append(f"check {c['name']} is from an older head")
        elif c["status"] != "completed":
            reasons.append(f"check {c['name']} is pending")
        elif c["conclusion"] not in GREEN:
            reasons.append(f"check {c['name']} failed")
    text = _unfenced(body)
    if re.search(r"^\s*(?:[-*+]|\d+[.)])\s+\[ \]", text, re.M):
        reasons.append("unticked box")
    reasons += [f"Needs the maintainer: {why}" for why in _maintainer_lines(text)]
    if any(f.startswith(VISIBLE) for f in files):
        reasons.append(MAINTAINER)
    return not reasons, reasons


def _norm(text):
    return " ".join(text.split())


def verdict(checks, gate_ok, gate_reasons, issue):
    """The verifier's (state, description) from its checks and the gate's result.

    A goal is grounded only with at least 3 words, verbatim in the issue text; otherwise it is not
    trusted. Every Done-when sentence needs a grounded check quoted from it. A check counts as run only when `ran` is True and `matches_goal` a bool."""
    grounded, ungrounded = [], []
    for c in checks:
        goal = _norm(c["goal"])
        if len(goal.split()) < 3 or goal not in _norm(issue):
            ungrounded.append(c["goal"])
        else:
            grounded.append(c)
    failed = [c["goal"] for c in grounded if _ran(c) and not c["matches_goal"]]
    if failed:
        return "failure", f"FAIL: {failed[0]}"
    if ungrounded:
        return "pending", "goal words not in the issue: " + "; ".join(ungrounded)
    not_run = [c["goal"] for c in grounded if not _ran(c)]
    if not_run:
        return "pending", "not run: " + "; ".join(not_run)
    unchecked = _unchecked(issue, [_norm(c["goal"]) for c in grounded])
    if unchecked:
        return "pending", "not checked: " + "; ".join(" ".join(i.split()[:8]) for i in unchecked)
    if not checks:
        return "pending", "no checks"
    return ("success", "PASS") if gate_ok else ("pending", "; ".join(gate_reasons))


BULLET = re.compile(r"\s*(\d+[.)]|[-*+])\s+")
AFTER_MERGE = re.compile(r"\bmerged\b|\bmerge commit\b", re.I)  # cannot be seen before the merge
POINTER = re.compile(r"\bDone-when (\d+)\b")


def _blocks(text):
    """Each `Done when` of the text as its list of items (a `Done when: …` line is a one-item list)."""
    blocks, items, gap = [], None, False
    for line in _unfenced(text).splitlines():
        bare = line.strip().lstrip("#").strip().strip("*").strip()
        if re.match(r"done when\b", bare, re.I):
            rest = re.sub(r"^done when[\s*]*(\(.*?\))?[\s*:]*", "", bare, flags=re.I).strip()
            items, gap = [], False
            blocks.append(items)
            if rest:
                items.append(rest)
                items = None
        elif items is None:
            continue
        elif not line.strip():
            gap = True
        elif m := BULLET.match(line):
            items.append(line[m.end():])
            gap = False
        elif items and not gap:
            items[-1] += " " + line.strip()
        else:
            items = None
    return blocks


def done_when(text):
    return [i for b in _blocks(text) for i in b]


def _unchecked(text, goals):
    """The Done-when sentences no goal is quoted from. A sentence about the merge is left out (it can be
    seen only after it); one pointing at `Done-when K` asks for that item of the epic's list instead."""
    lists = [b for b in _blocks(text) if len(b) > 1]
    out = []
    for item in done_when(text):
        for sentence in re.split(r"(?<=[.!?])\s+", _norm(item)):
            if not sentence or AFTER_MERGE.search(sentence):
                continue
            if m := POINTER.search(sentence):
                if not any(len(b) >= int(m[1]) for b in lists):
                    out.append(sentence + " (its item is not in the text)")
                continue
            if not any(g in sentence for g in goals):
                out.append(sentence)
    return out


def _ran(c):
    return c["ran"] is True and isinstance(c["matches_goal"], bool)


def _well_formed(checks):
    return isinstance(checks, list) and all(
        isinstance(c, dict) and isinstance(c.get("goal"), str) and {"ran", "matches_goal", "saw"} <= c.keys()
        for c in checks)


def _unfenced(body):
    return re.sub(r"^\s*(```|~~~).*?^\s*\1", "", body, flags=re.S | re.M)


def _maintainer_lines(text):
    return [w.strip() for w in re.findall(r"^\s*(?:[-*+]\s+)?\**Needs the maintainer:\**(.*)$", text, re.M)]


def attention(pr):
    """What an open PR (a `gh pr list --json` row) needs, one line each; [] when nothing."""
    n, rollup = f"#{pr['number']}", pr["statusCheckRollup"] or []
    lines = [f"{n} conflicts with {pr['baseRefName']}"] if pr["mergeable"] == "CONFLICTING" else []
    failed = [c["name"] for c in rollup if "name" in c and c["status"] == "COMPLETED" and c["conclusion"].lower() not in GREEN]
    lines += [f"{n}: {failed[0]} failed"] if failed else []
    lines += [] if rollup else [f"{n}: no checks ran"]
    verify = next((c for c in rollup if c.get("context") == "verify"), None)
    if verify is None:  # not verified yet: the body says what it waits for
        return lines + [f"{n}: needs the maintainer: {w}" for w in _maintainer_lines(_unfenced(pr["body"]))]
    state = verify["state"]
    if state == "SUCCESS":
        return lines + [f"{n}: verified, not merged"]
    word = "pending" if state == "PENDING" else "failed"
    return lines + [f"{n}: verify {word}: {verify['description']}"]


def _gh(args, timeout=None):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, check=True, timeout=timeout).stdout
    return json.loads(out)


def _open(run):
    try:
        prs = run(["pr", "list", "--author", "@me", "--state", "open",
                   "--json", "number,baseRefName,mergeable,statusCheckRollup,body"])
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0  # no gh, signed out or offline: say nothing
    lines = [line for pr in prs for line in attention(pr)]
    if lines:
        print("\n".join(["Open PRs that need you:", *lines]))
    return 0


def _option(argv, name):
    return argv[argv.index(name) + 1] if name in argv else None


def _verdict_out(checks_file, gate_ok, reasons, sha, issue):
    try:
        with open(checks_file) as f:
            checks = json.load(f)
    except (OSError, ValueError):
        checks = None
    if _well_formed(checks):
        state, description = verdict(checks, gate_ok, reasons, issue)
    else:
        state, description = "pending", "bad checks file"
    print(json.dumps({"state": state, "description": description[:140], "reasons": reasons, "sha": sha}))
    return 0 if state == "success" else 1


def _trusted(n, run):
    try:
        item = run(["api", f"repos/{REPO}/issues/{n}"])  # a PR too: GitHub's PRs are issues
        subs = [] if "pull_request" in item else [
            s for page in run(["api", "--paginate", "--slurp", f"repos/{REPO}/issues/{n}/sub_issues?per_page=100"])
            for s in page]
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        print(json.dumps({"trusted": False, "error": f"gh failed: {(getattr(e, 'stderr', None) or e)}".strip()}))
        return 1
    author = item["user"]["login"]
    strangers = [s["number"] for s in subs if s["user"]["login"] != OWNER]
    print(json.dumps({"trusted": author == OWNER, "author": author, "strangers": strangers}))
    return 0 if author == OWNER else 1


def main(argv=None, run=_gh):
    argv = sys.argv[1:] if argv is None else argv
    checks_file, issue_file = _option(argv, "--checks"), _option(argv, "--issue")
    if checks_file and issue_file:  # offline, for a spike: no gh, the gate counts as ok
        with open(issue_file) as f:
            return _verdict_out(checks_file, True, [], None, f.read())
    pr = argv[0] if argv else None
    if pr == "--trusted" and len(argv) > 1:
        return _trusted(argv[1], run if run is not _gh else (lambda args: _gh(args, timeout=30)))
    if pr == "--open":
        return _open(run if run is not _gh else (lambda args: _gh(args, timeout=5)))
    if not checks_file or not pr or pr.startswith("--"):
        print("usage: decide.py <pr> --checks <file> | --checks <file> --issue <file> | --open | --trusted <n>", file=sys.stderr)
        return 2
    try:
        view = run(["pr", "view", pr, "--json", "headRefOid,body,author,closingIssuesReferences"])
        sha = view["headRefOid"]
        closing = [run(["issue", "view", str(i["number"]), "--json", "body,author"]) | {"number": i["number"]}
                   for i in view.get("closingIssuesReferences", [])]
        pages = run(["api", "--paginate", "--slurp", f"repos/{REPO}/commits/{sha}/check-runs?per_page=100"])
        files = run(["api", "--paginate", "--slurp", f"repos/{REPO}/pulls/{pr}/files?per_page=100"])
    except subprocess.CalledProcessError as e:
        why = f"gh failed: {(e.stderr or '').strip()}"
        print(json.dumps({"state": "pending", "description": why[:140], "reasons": [why], "sha": None}))
        return 1
    checks = [c for page in pages for c in page["check_runs"] if c["name"] != "verify"]
    paths = [f["filename"] for page in files for f in page]
    issues = [(i["number"], i["author"]["login"]) for i in closing]
    ok, reasons = decide(checks, view["body"], paths, sha, view["author"]["login"], issues)
    text = "\n".join(i["body"] for i in closing) if closing else view["body"]
    return _verdict_out(checks_file, ok, reasons, sha, text)


if __name__ == "__main__":
    sys.exit(main())
