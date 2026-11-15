"""Run one Claude Code skill for real against a test world, with a stand-in user (#33).

The conversation is the real model, on the plan the local `claude` is signed in to (no API key: it is
cleared). The `door` MCP server is the test world's (`app/test/world/boot.py`: the real server, only its
edges replaced; its own model calls go to the stand-in `claude.py`), so nothing leaves the computer and
nothing touches the user's own data. The user is a second, small model playing the persona: it answers
each plain-text question and each AskUserQuestion from the persona's facts and wishes.

    python tests/skills/skill_run.py <world.json> "/onboard" [--model sonnet] [--max-turns 12] [--out DIR]
        [--stop-after TOOL] [--persona-kind onboarding|onboarded] [--facts-note "what the user wants"]

<world.json> is what `npx tsx app/test/world/make-world.ts <persona>` prints (`--empty` for a user with no data
yet, as /onboard wants; without it mette's profile, ledger and ads exist, as /expand, /upskill and a review want). Writes
`transcript.md` and `result.json` (tool calls, AskUserQuestion answers, the files in the home) to --out.
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

REPO = Path(__file__).resolve().parents[2]

USER_RULES = """You play a person setting up a job-search app called The other door in a chat with its assistant.
Stay in character and answer the assistant's last message the way this person would: briefly, plainly,
in English, one to three sentences. Never invent facts beyond the ones below; if asked for something you
don't know, say you don't have it. You don't use the app on another computer and don't want Google Drive.
You don't want any employer discovery source (LinkedIn or others) turned on. When the assistant shows you a
review or summary and asks you to confirm, look it over and confirm it if it matches your facts; if something
is wrong, say exactly what. When asked for your CV or sources, give the path of your CV file.

Your facts:
{facts}
"""


ONBOARDED_RULES = """You play a person who already set up a job-search app called The other door and uses it in a chat
with its assistant. Stay in character and answer the assistant's last message the way this person would:
briefly, plainly, in English, one to three sentences. Never invent facts beyond the ones below. You ask for
nothing new: you do not want a new search, a prepared application or a changed status unless the assistant
offers it and it fits your wish below. When the assistant asks whether there is anything else, or whether you
are finished, say "I'm done". When asked which of several options you mean, pick the first. When asked
for a role, a job or a number to analyse, use the one in your wish below.

Your facts:
{facts}
"""


def user_rules(kind: str = "onboarding", facts_note: str = "") -> str:
    """The stand-in user's system prompt (facts still to be filled in): setting up, or already set up."""
    rules = ONBOARDED_RULES if kind == "onboarded" else USER_RULES
    return rules + (f"\nYour wish for this chat: {facts_note}\n" if facts_note else "")


def finished(stop_after_tool: str, tools: list[str]) -> bool:
    """A run is over once the tool that ends its journey has been called."""
    return stop_after_tool in tools


def no_api_key_env() -> dict[str, str]:
    """The real `claude` runs on its sign-in: an API key in the environment would be billed instead."""
    return {"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": ""}


def ask_user(facts: str, prompt: str, schema: dict | None = None, rules: str | None = None) -> str:
    """One answer from the stand-in user: a small model, on the same sign-in."""
    cmd = ["claude", "-p", "--model", "haiku", "--output-format", "json", "--tools", "",
           "--no-session-persistence", "--system-prompt", (rules or USER_RULES).format(facts=facts)]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    env = {**os.environ, **no_api_key_env()}
    out = subprocess.run(cmd, input=prompt, capture_output=True, text=True, env=env, timeout=180)
    envelope = json.loads(out.stdout)
    if schema and envelope.get("structured_output") is not None:
        return json.dumps(envelope["structured_output"])
    return envelope.get("result", "")


def answer_questions(facts: str, questions: list[dict], rules: str | None = None) -> dict[str, str]:
    """AskUserQuestion's answers, {question text: chosen label(s), comma-separated}, picked by the user."""
    shown = json.dumps([{k: q.get(k) for k in ("question", "multiSelect", "options")} for q in questions], indent=1)
    schema = {"type": "object", "properties": {"answers": {"type": "array", "items": {
        "type": "object", "properties": {"question": {"type": "string"}, "labels": {"type": "array", "items": {"type": "string"}},
                                         "other": {"type": "string"}},
        "required": ["question", "labels"]}}}, "required": ["answers"]}
    raw = ask_user(facts, "The assistant asks you these questions, each with its options. For each question pick the "
                          "option label(s) that fit you (several only where multiSelect is true); if none fits, give no label "
                          "and write your own answer in `other`.\n\n" + shown, schema, rules)
    try:
        picked = json.loads(raw)["answers"]
    except (ValueError, KeyError, TypeError):
        picked = []
    by_text = {p.get("question"): p for p in picked if isinstance(p, dict)}
    answers = {}
    for q in questions:
        p = by_text.get(q["question"]) or {}
        labels = [l for l in p.get("labels", []) if any(o.get("label") == l for o in q.get("options", []))]
        answers[q["question"]] = ", ".join(labels) if labels else (p.get("other") or q["options"][0]["label"])
    return answers


async def run(world: dict, prompt: str, model: str, max_turns: int, out: Path, *, stop_after_tool: str = "find_jobs",
               persona_kind: str = "onboarding", facts_note: str = "") -> dict:
    persona = {k: v for k, v in world["persona"].items() if k != "cv"}
    facts = json.dumps({**persona, "cv_file": world["cvFile"]}, ensure_ascii=False, indent=1)
    rules = user_rules(persona_kind, facts_note)
    transcript: list[str] = [f"**user:** {prompt}"]
    asked: list[dict] = []
    denied: list[dict] = []
    used: list[dict] = []   # every tool the conversation used besides door's, with its input

    async def can_use_tool(name, data, _context):
        if name == "AskUserQuestion":
            answers = answer_questions(facts, data.get("questions", []), rules)
            asked.append({"at": time.time(), "questions": data.get("questions", []), "answers": answers})
            transcript.append("**AskUserQuestion:** " + json.dumps(answers, ensure_ascii=False))
            return PermissionResultAllow(updated_input={**data, "answers": answers})
        if name.startswith("mcp__door__"):
            return PermissionResultAllow(updated_input=data)
        if name in ("Read", "Edit") and _inside(data.get("file_path", ""), world["home"]):
            return PermissionResultAllow(updated_input=data)
        denied.append({"tool": name, "input": data})
        transcript.append(f"**denied:** {name} {json.dumps(data, ensure_ascii=False)[:300]}")
        return PermissionResultDeny(message=f"{name} is not allowed in this test")

    server_env = {**world["env"], "PYTHONPATH": str(REPO / "src")}
    options = ClaudeAgentOptions(
        cwd=str(REPO),
        cli_path=shutil.which("claude"),
        model=model,
        setting_sources=["project"],
        mcp_servers={"door": {"type": "stdio", "command": world["env"]["DOOR_PYTHON"], "args": [], "env": server_env}},
        strict_mcp_config=True,
        can_use_tool=can_use_tool,
        env=no_api_key_env(),
    )
    cost = 0.0
    turns = 0
    async with ClaudeSDKClient(options=options) as client:
        message = prompt
        while turns < max_turns:
            turns += 1
            await client.query(message)
            said: list[str] = []
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            said.append(block.text)
                            transcript.append(f"**claude:** {block.text}")
                        elif isinstance(block, ToolUseBlock):
                            if not block.name.startswith("mcp__door__") and block.name != "AskUserQuestion":
                                used.append({"tool": block.name, "input": block.input})
                            transcript.append(f"`{block.name}` {json.dumps(block.input, ensure_ascii=False)[:400]}")
                elif isinstance(msg, ResultMessage):
                    cost += msg.total_cost_usd or 0
            if finished(stop_after_tool, [c.get("tool") for c in calls(world)]):
                break
            reply = ask_user(facts, "The assistant said:\n\n" + "\n\n".join(said[-2:]) + "\n\nYour reply:", rules=rules)
            transcript.append(f"**user:** {reply}")
            message = reply

    result = {
        "turns": turns,
        "cost_usd_equivalent": round(cost, 4),
        "tools": [c.get("tool") for c in calls(world) if c.get("kind") == "tool"],
        "calls": [c for c in calls(world) if c.get("kind") == "tool"],
        "asked": asked,
        "denied": denied,
        "used": used,
        "files": sorted(str(p.relative_to(world["home"])) for p in Path(world["home"]).rglob("*") if p.is_file()),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "transcript.md").write_text("\n\n".join(transcript) + "\n", encoding="utf-8")
    (out / "result.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return result


def _inside(path: str, folder: str) -> bool:
    try:
        Path(path).resolve().relative_to(Path(folder).resolve())
        return True
    except (ValueError, OSError):
        return False


def calls(world: dict) -> list[dict]:
    path = Path(world["dir"]) / "calls.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.exists() else []


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("world")
    parser.add_argument("prompt")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--out", default="skill-run")
    parser.add_argument("--stop-after", default="find_jobs", help="end the run once this tool was called")
    parser.add_argument("--persona-kind", choices=("onboarding", "onboarded"), default="onboarding")
    parser.add_argument("--facts-note", default="", help="what the user wants from this chat")
    args = parser.parse_args(argv)
    world = json.loads(Path(args.world).read_text(encoding="utf-8"))
    result = asyncio.run(run(world, args.prompt, args.model, args.max_turns, Path(args.out),
                                  stop_after_tool=args.stop_after, persona_kind=args.persona_kind, facts_note=args.facts_note))
    json.dump({k: result[k] for k in ("turns", "cost_usd_equivalent", "tools", "files")}, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
