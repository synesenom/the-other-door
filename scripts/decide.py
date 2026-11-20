#!/usr/bin/env python3
"""Whether a PR's head has what the verifier needs to pass it: `python scripts/decide.py <pr>`.

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
    text = re.sub(r"^\s*(```|~~~).*?^\s*\1", "", body, flags=re.S | re.M)
    if re.search(r"^\s*(?:[-*+]|\d+[.)])\s+\[ \]", text, re.M):
        reasons.append("unticked box")
    for why in re.findall(r"^\s*(?:[-*+]\s+)?\**Needs the maintainer:\**(.*)$", text, re.M):
        reasons.append(f"Needs the maintainer: {why.strip()}")
    if any(f.startswith(VISIBLE) for f in files):
        reasons.append(MAINTAINER)
    return not reasons, reasons


def _gh(args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def main(argv=None, run=_gh):
    pr = (sys.argv[1:] if argv is None else argv)[0]
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
