"""A stand-in `claude` for the journeys: first on the server's PATH, it plays the real CLI at its
process boundary. Run as `python claude.py <world dir> <claude's own arguments>`.

- `auth status --json` / `auth login`: signed in when `<world>/claude-signed-in` exists; `auth login`
  prints its page and the paste prompt as claude 2.1 does over pipes, and the code `world-code#ok`
  signs in (any other code fails as a bad code does).
- `-p` calls are told apart by the words of their system prompt (or, for `revise`, of stdin) and
  answered from `world.json`: scores and English titles by the ad's title and company, the
  onboarding and CV answers from `answers`, the tailor by writing the .tex files and running door's
  own `compile` (whose LaTeX is the stand-in tectonic).
- `faults.json`'s `claude` map makes one kind of call fail (`{"fail": "message"}`), wait first
  (`delay_s`), or answer something else (`answer`). Every call is logged to `calls.jsonl`.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

WORLD = Path(sys.argv[1])
ARGS = sys.argv[2:]
SIGNED_IN = WORLD / "claude-signed-in"


def world() -> dict:
    return json.loads((WORLD / "world.json").read_text(encoding="utf-8"))


def faults() -> dict:
    try:
        return json.loads((WORLD / "faults.json").read_text(encoding="utf-8")).get("claude", {})
    except (OSError, ValueError):
        return {}


def log(kind: str, **fields) -> None:
    with (WORLD / "calls.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "claude", "call": kind, "at": time.time(), **fields}) + "\n")


def arg(name: str) -> str | None:
    return ARGS[ARGS.index(name) + 1] if name in ARGS and ARGS.index(name) + 1 < len(ARGS) else None


def envelope(result) -> None:
    sys.stdout.write(json.dumps({"type": "result", "is_error": False, "result": result if isinstance(result, str) else json.dumps(result)}))


# --------------------------------------------------------------------------- not model calls
if ARGS[:1] == ["--version"]:
    print("2.1.310 (Claude Code)")
    sys.exit(0)
if ARGS[:2] == ["auth", "status"]:
    if SIGNED_IN.exists():
        print(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "email": world().get("persona", {}).get("email", "someone@example.com"), "subscriptionType": "max"}))
        sys.exit(0)
    print(json.dumps({"loggedIn": False, "authMethod": "none"}))
    sys.exit(1)
if ARGS[:2] == ["auth", "login"]:
    (WORLD / "claude-login-args").write_text(" ".join(ARGS), encoding="utf-8")
    print("Opening browser to sign in…", flush=True)
    print("If the browser didn't open, visit: https://claude.com/cai/oauth/authorize?code=true&state=world", flush=True)
    sys.stdout.write("Paste code here if prompted > ")
    sys.stdout.flush()
    code = sys.stdin.readline().strip()
    if code == "world-code#ok":
        # `{"claude": {"login": {"stay_signed_out": true}}}`: claude says it worked, `auth status` still says signed out.
        if not faults().get("login", {}).get("stay_signed_out"):
            SIGNED_IN.touch()
        print("Login successful.")
        sys.exit(0)
    sys.stderr.write("Login failed: Request failed with status code 400\n")
    sys.exit(1)

# --------------------------------------------------------------------------- model calls
SYSTEM = arg("--system-prompt") or ""
# a call that hangs before it answers still leaves a trace: how it was started (#18)
with (WORLD / "claude-starts.jsonl").open("a", encoding="utf-8") as _f:
    _f.write(json.dumps({"at": time.time(), "args": len(ARGS), "chars": sum(map(len, ARGS)), "stdin_tty": sys.stdin.isatty(),
                         "agent": arg("--agent"), "model": arg("--model")}) + "\n")
# The tailor (`--agent`) has its prompt in the arguments and inherits the server's stdin, the MCP pipe that
# never closes: reading it would wait forever.
STDIN = sys.stdin.read() if not sys.stdin.isatty() and arg("--agent") is None else ""
TEXT = SYSTEM + "\n" + STDIN

KINDS = [
    ("score", "job-matching scorer"),
    ("translate", "You translate job titles into English"),
    ("read_ad", "You read a job ad."),
    ("enrich", "You enrich a job seeker's CV"),
    ("draft", "You draft a job seeker's CV"),
    ("stories", "You draft CARL stories"),
    ("basics", "You read a job seeker's CV and fill in"),
    ("keywords", "You propose search terms"),
    ("titles", "You suggest the job titles"),
    ("gaps", "You write a skill-gap analysis"),
    ("revise", "You are revising the body of a LaTeX"),
    ("market", "You group skill names"),
    ("ask", "You answer one question about the user's job search"),
    ("careers", "You find the official careers page"),
]
kind = "tailor" if arg("--agent") == "tailor" else next((k for k, words in KINDS if words in TEXT), "unknown")
log(kind, model=arg("--model"))

said = faults().get(kind, {})
time.sleep(said.get("delay_s", 0))
if said.get("fail"):
    sys.stderr.write(said["fail"] + "\n")
    sys.exit(1)
if kind == "unknown":
    sys.stderr.write("the test world has no answer for this claude call\n")
    sys.exit(97)
W = world()


def scored(title: str, company: str) -> dict:
    found = W.get("scores", {}).get(f"{title}|{company}")
    if found is None:
        return {"score": 0.42, "score_reason": "Some overlap with the CV, but the role leans elsewhere.", "matching_skills": [], "missing_skills": []}
    return found


if kind == "score":
    results = []
    for block in re.split(r"^### job_id: ", STDIN, flags=re.M)[1:]:
        job_id, _, rest = block.partition("\n")
        title = re.search(r"^Title: (.*)$", rest, re.M)
        company = re.search(r"^Company: (.*)$", rest, re.M)
        s = scored(title.group(1) if title else "", company.group(1) if company else "")
        results.append({
            "job_id": job_id.strip(), "score": s["score"], "score_reason": s["score_reason"],
            "matching_skills": s.get("matching_skills", []), "missing_skills": s.get("missing_skills", []),
            "language_requirement": s.get("language_requirement", "none"), "work_permit": "not_mentioned", "flags": [],
        })
    if not results:  # a single posting, not a chunk
        title = re.search(r"^Title: (.*)$", STDIN, re.M)
        company = re.search(r"^Company: (.*)$", STDIN, re.M)
        s = scored(title.group(1) if title else "", company.group(1) if company else "")
        envelope(said.get("answer") or {
            "score": s["score"], "score_reason": s["score_reason"], "matching_skills": s.get("matching_skills", []),
            "missing_skills": s.get("missing_skills", []), "language_requirement": s.get("language_requirement", "none"),
            "work_permit": "not_mentioned", "flags": [],
        })
    else:
        envelope(said.get("answer") or {"results": results})
elif kind == "translate":
    items = json.loads(STDIN)
    titles = W.get("titles_en", {})
    envelope({"titles": [{"id": i["id"], "title_en": titles.get(i["title"], i["title"])} for i in items]})
elif kind == "read_ad":
    found = next((a for a in W.get("read_ads", []) if a["title"] in STDIN), None)
    envelope(said.get("answer") or found or {"title": "", "company": "", "location": ""})
elif kind == "market":
    names = json.loads(STDIN).get("names", [])
    envelope({"groups": [{"variant": n, "canonical": n, "skill": True} for n in names]})
elif kind == "revise":
    body = STDIN.split("Current body:\n", 1)[-1].strip()
    paragraphs = [p for p in body.split("\n\n") if p.strip()]
    if len(paragraphs) > 2:
        paragraphs = paragraphs[:-1]  # every instruction here makes it shorter: the last paragraph goes
    envelope("\n\n".join(paragraphs))  # revise reads the envelope of a stream-json run
elif kind == "tailor":
    import subprocess

    out = Path.cwd()
    job_id = out.name
    jobs = out.parent.parent
    posting = json.loads((jobs / ".tailor" / job_id / "posting.json").read_text(encoding="utf-8"))
    (out / "posting.json").write_text(json.dumps(posting), encoding="utf-8")
    tailored = W.get("tailor", {})
    for name in ("cv", "cover_letter"):
        tex = said.get(name) or tailored.get(name, "")
        (out / f"{name}.tex").write_text(tex, encoding="utf-8")
    compiled = subprocess.run(
        [os.environ.get("DOOR_WORLD_PYTHON", sys.executable), "-c",
         "import sys; from door.commands import compile as c; c._compile_core(sys.argv[1], render=True)", job_id],
        capture_output=True, text=True,
    )
    if compiled.returncode != 0:
        sys.stderr.write(compiled.stderr)
        sys.exit(1)
    print("Tailored the CV and the cover letter.")
else:
    answer = said.get("answer") or W.get("answers", {}).get(kind)
    if answer is None:
        sys.stderr.write(f"the test world has no {kind} answer\n")
        sys.exit(97)
    if arg("--json-schema"):
        envelope(answer)
    else:
        sys.stdout.write(answer if isinstance(answer, str) else json.dumps(answer))
