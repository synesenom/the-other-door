"""`ask`: one question about the jobs data, answered in a sentence or two (#339).

One `claude -p` call (Haiku by default) on the user's plan, with the door MCP server and only its
read tools allowed (`ASK_TOOLS`, each in `mcp_server.READ_ONLY_TOOLS`); the shell, file and writing
tools are refused outright. So asking can never change profile/ or jobs/. The answer is JSON: the
words, optionally where the app can show it (`go_to`, its job ids checked against the postings on
disk), and which tools it came from.
"""

import json
from pathlib import Path

import click

from door.commands import _common as common
from door.core import claude_cli, selection, workspace

# The tools the model may call: reading only. Left out: `market` (it saves a report by default), `show`
# (it can open the PDF viewer and render page images) and `ask` itself (no recursion).
ASK_TOOLS = ("status_summary", "list_matches", "show_profile", "query_jobs", "list_companies", "why_company")
# Refused even if the model asks: the shell and files, and every writing tool by name.
_REFUSED = ("Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch", "Agent", "NotebookEdit")
SCREENS = ("matches", "posting", "applications", "employers", "cv")
_DEFAULT_MODEL = "haiku"
_TIMEOUT_S = 180

_RULES = """You answer one question about the user's job search in The other door, from The other door's tools only.

- Call the tools to find the answer: status_summary (the dashboard: runs, matches, the ledger, interview
  rounds), list_matches (the matches, or a status, or ongoing), query_jobs (counts and the best rows by date, site, company, status, score, language), list_companies
  and why_company (the employers followed), show_profile (the profile and the CV).
- Answer only from what the tools return. When they cannot answer, say "I don't know" and what is known.
- One or two short sentences. Name postings by their title and company, never by an id or a path.
- When a screen shows the answer, set go_to: "matches" (the matches), "applications" (jobs in play),
  "posting" (one job: its id in job_ids), "employers" (the followed employers) or "cv" (the CV). Put the
  ids of the jobs you mean in job_ids, taken from the tools. Leave go_to out otherwise.
- sources: the tools the answer came from."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "go_to": {
            "type": "object",
            "properties": {"screen": {"type": "string", "enum": list(SCREENS)}, "job_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["screen"],
        },
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer"],
}


def _writing_tools() -> list[str]:
    from door import mcp_server

    return sorted(mcp_server.WRITING_TOOLS)


def _ask_core(question: str, *, model: str | None = None, jobs_dir: Path | None = None, profile_dir: Path | None = None) -> dict:
    """Answer `question` from the read tools. Never prints, never writes.

    Returns:
        ``{"answer", "go_to": {"screen", "job_ids"?} | None, "sources": [tool, ...]}``; `go_to`'s job ids
        are only ones on disk, and an unknown screen drops it.

    Raises:
        ValueError: an empty question.
        claude_cli.ClaudeError: the call failed, timed out, or did not answer in the asked shape.
    """
    question = (question or "").strip()
    if not question:
        raise ValueError("ask a question")
    jobs_dir = Path(jobs_dir or workspace.JOBS_DIR)
    mcp_config = workspace.ensure_mcp_config()
    args = [
        "--model", model or _DEFAULT_MODEL,
        "--system-prompt", _RULES,
        "--json-schema", json.dumps(_SCHEMA), *claude_cli.STREAM_ARGS,
        "--mcp-config", str(mcp_config),
        "--strict-mcp-config",  # The other door's server only: never the user's own MCP servers or connectors
        "--tools", "",  # no built-in tool (shell, files, web): only the MCP tools allowed below
        "--allowedTools", ",".join(f"mcp__door__{t}" for t in ASK_TOOLS),
        "--disallowedTools", ",".join([*_REFUSED, *(f"mcp__door__{t}" for t in [*_writing_tools(), "ask"])]),
        "--no-session-persistence",
    ]
    stdout = claude_cli.run(args, feature="ask", input=question, timeout_s=_TIMEOUT_S, profile_dir=profile_dir)
    data = claude_cli.json_result(stdout)
    if not isinstance(data, dict) or not isinstance(data.get("answer"), str) or not data["answer"].strip():
        raise claude_cli.ClaudeError("claude did not answer the question")
    go_to = data.get("go_to")
    if isinstance(go_to, dict) and go_to.get("screen") in SCREENS:
        known = {p.get("id") for p in selection.read_postings(jobs_dir)}
        ids = [i for i in go_to.get("job_ids") or [] if isinstance(i, str) and i in known]
        go_to = {"screen": go_to["screen"], **({"job_ids": ids} if ids else {})}
        if go_to["screen"] == "posting" and not ids:
            go_to = None
    else:
        go_to = None
    sources = [s for s in data.get("sources") or [] if isinstance(s, str)]
    return {"answer": data["answer"].strip(), "go_to": go_to, "sources": sources}


@click.command("ask")
@click.argument("question", nargs=-1, required=True)
@click.option("--model", default=None, help=f"Claude model to answer with (default: {_DEFAULT_MODEL}).")
def ask(question: tuple[str, ...], model: str | None):
    """Ask a question about your jobs data, in your own words.

    `./door ask "how many jobs did I apply to last month?"`: one short Claude call on your plan,
    reading only (it can never change your data)."""
    try:
        result = _ask_core(" ".join(question), model=model, jobs_dir=workspace.JOBS_DIR, profile_dir=workspace.PROFILE_DIR)
    except (ValueError, claude_cli.ClaudeError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from None
    console = common._console()
    console.print(result["answer"])
    go_to = result["go_to"]
    if go_to and go_to.get("job_ids"):
        by_id = {p.get("id"): p for p in selection.read_postings(workspace.JOBS_DIR)}
        names = [f"{by_id[i].get('title', '')} · {by_id[i].get('company', '')}" for i in go_to["job_ids"] if i in by_id]
        console.print("See: " + "; ".join(names))
