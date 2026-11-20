#!/usr/bin/env python3
"""Whether a PR's head has what the verifier needs to pass it: `python scripts/decide.py <pr>`.

`python scripts/decide.py --open` lists the user's open PRs that need something (the
session-start hook): a conflict, a failed or missing check, the `verify` status, or, before the
verifier has spoken, the body's `Needs the maintainer:` lines, read as the gate reads them.

Prints {"ok", "reasons", "sha"} and exits 0 when ok, 1 otherwise. Reads the PR and its head's
check runs through `gh`; the `verify` check (the verifier's own status) is left out. A PR that
changes what a user sees is never ok: the maintainer looks at it.
"""

import json
import re
import subprocess
import sys

REPO = "synesenom/the-other-door"
GREEN = {"success", "skipped", "neutral"}
VISIBLE = ("app/src/renderer/", "app/src/web/", "app/src/preview/", "docs/design/")
MAINTAINER = "Needs the maintainer: look at it"


def decide(checks, body, files, head):
    """Return (ok, reasons) for a head's check runs, the PR body and the changed file paths."""
    reasons = []
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


def main(argv=None, run=_gh):
    pr = (sys.argv[1:] if argv is None else argv)[0]
    if pr == "--open":
        return _open(run if run is not _gh else (lambda args: _gh(args, timeout=5)))
    try:
        view = run(["pr", "view", pr, "--json", "headRefOid,body"])
        sha = view["headRefOid"]
        pages = run(["api", "--paginate", "--slurp", f"repos/{REPO}/commits/{sha}/check-runs?per_page=100"])
        files = run(["api", "--paginate", "--slurp", f"repos/{REPO}/pulls/{pr}/files?per_page=100"])
    except subprocess.CalledProcessError as e:
        print(json.dumps({"ok": False, "reasons": [f"gh failed: {(e.stderr or '').strip()}"], "sha": None}))
        return 1
    checks = [c for page in pages for c in page["check_runs"] if c["name"] != "verify"]
    paths = [f["filename"] for page in files for f in page]
    ok, reasons = decide(checks, view["body"], paths, sha)
    print(json.dumps({"ok": ok, "reasons": reasons, "sha": sha}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
