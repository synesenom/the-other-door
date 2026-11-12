"""Play a Claude Code review session in this terminal, for the demo GIF.

    claude_session.py --seed    the run the session follows (record.sh, before recording)
    claude_session.py           the session (claude.tape types it in VHS, as `claude`)

It is not Claude Code: it draws a session in Claude Code's style, but every tool call in
it is the real door MCP tool (`door.mcp_server`), called in the sandbox through
`shim.py`'s stubs, and what the tool returns is what is shown. Only the user's prompts and
Claude's replies are scripted (`TURNS`), and the replies are written from those results, so
the GIF follows `postings.py` when it changes.

The prompts are typed by the script, a key at a time; VHS records the terminal with the
CLI tapes' settings, so the GIFs share a size, theme and window. `--seed` has The other door's
`find` scrape and score the demo boards first (fast, unrecorded), so the session opens on a
run's worth of new matches, as a real review session would.
"""

import asyncio
import json
import os
import shutil
import sys
import textwrap
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import shim  # noqa: E402

SANDBOX = Path(os.environ["DOOR_DEMO_DIR"])
shim.install(SANDBOX)

from door import mcp_server as tools  # noqa: E402

ORANGE = "\x1b[38;2;215;119;87m"
GREEN = "\x1b[38;2;78;186;101m"
GREY = "\x1b[38;5;245m"
BOLD = "\x1b[1m"
RESET = "\x1b[0m"
SPINNER = "·✢✶✻✽✻✶✢"  # no ✳: it has an emoji form
PREVIEW_LINES = 2
THINK_S = 1.0
LINE_S = 0.05
KEY_S = 0.06  # typing speed, as in the CLI tapes
READ_S = 2.5  # pause on each answer before the next prompt is typed

WIDTH = shutil.get_terminal_size().columns
WRITE_LOCK = threading.Lock()


def _write(text: str) -> None:
    with WRITE_LOCK:
        sys.stdout.write(text)
        sys.stdout.flush()


def _clip(text: str, width: int = WIDTH - 2) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _bold(text: str) -> str:
    """`**x**` → bold, the one bit of markdown the replies use."""
    parts = text.split("**")
    return "".join(p if i % 2 == 0 else BOLD + p + RESET for i, p in enumerate(parts))


def _rel(path: str) -> str:
    return str(Path(path).relative_to(SANDBOX))


class Live:
    """The block at the bottom that is redrawn in place (spinner, a running tool's progress)."""

    def __init__(self):
        self.lines: list[str] = []
        self.status = ""
        self.verb = ""
        self.started = 0.0
        self._drawn = 0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def _render(self) -> None:
        tick = int((time.monotonic() - self.started) / 0.12)
        seconds = int(time.monotonic() - self.started)
        spinner = f"{ORANGE}{SPINNER[tick % len(SPINNER)]} {self.verb}… {GREY}({seconds}s · esc to interrupt){RESET}"
        progress = [f"  └  {GREY}{_clip(self.status, WIDTH - 8)}{RESET}"] if self.status else []
        lines = [*self.lines, *progress, "", spinner]
        out = f"\x1b[{self._drawn}F\x1b[J" if self._drawn else ""
        _write(out + "".join(line + "\n" for line in lines))
        self._drawn = len(lines)

    def _loop(self) -> None:
        while not self._stop.wait(0.12):
            with self._lock:
                self._render()

    def start(self, verb: str, lines: list[str] | None = None) -> None:
        self.verb, self.lines, self.status = verb, lines or [], ""
        self.started = time.monotonic()
        self._stop.clear()
        with self._lock:
            self._render()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Erase the block; the caller prints what stays."""
        self._stop.set()
        self._thread.join()
        with self._lock:
            _write(f"\x1b[{self._drawn}F\x1b[J")
            self._drawn = 0


LIVE = Live()


class Ctx:
    """The MCP `Context` a client would pass: progress notifications land on the tool's line."""

    async def report_progress(self, progress, total=None, message=None) -> None:
        LIVE.status = message or ""


def think(seconds: float = THINK_S) -> None:
    LIVE.start("Thinking")
    time.sleep(seconds)
    LIVE.stop()


def call(name: str, **args) -> dict:
    """Run the real MCP tool `name`, drawing its call the way Claude Code shows an MCP tool."""
    shown = ", ".join(f"{k}: {json.dumps(v)}" for k, v in args.items())
    header = f"{GREEN}●{RESET} {BOLD}door - {name} (MCP){RESET}({shown})"
    fn = getattr(tools, name)
    if asyncio.iscoroutinefunction(fn):
        args["ctx"] = Ctx()
    box: dict = {}
    LIVE.start("Working", [header])
    started = time.monotonic()

    def work():
        result = fn(**args)
        box["result"] = asyncio.run(result) if asyncio.iscoroutine(result) else result

    worker = threading.Thread(target=work)
    worker.start()
    worker.join()
    time.sleep(max(0.0, 0.9 - (time.monotonic() - started)))
    LIVE.stop()
    result = box["result"]
    body = json.dumps(result, indent=2, default=str).splitlines()
    lines = [header] + [
        ("  └  " if i == 0 else "     ") + GREY + _clip(line, WIDTH - 8) + RESET
        for i, line in enumerate(body[:PREVIEW_LINES])
    ]
    if len(body) > PREVIEW_LINES:
        lines.append(f"     {GREY}… +{len(body) - PREVIEW_LINES} lines (ctrl+o to expand){RESET}")
    _write("".join(line + "\n" for line in lines) + "\n")
    return result


def say(*paragraphs: str) -> None:
    """Claude's reply: a ● and the text, streamed a line at a time."""
    lines = []
    for paragraph in paragraphs:
        if lines:
            lines.append("")
        for raw in paragraph.splitlines():
            if raw.startswith(("  ", "- ")):
                lines.append(raw)
            else:
                lines.extend(textwrap.wrap(raw, WIDTH - 6) or [""])
    for i, line in enumerate(lines):
        _write(("● " if i == 0 else "  ") + _bold(line) + "\n")
        time.sleep(LINE_S)
    _write("\n")


def input_box() -> None:
    """Draw the empty input box and leave the cursor after its `> `."""
    rule = GREY + "─" * WIDTH + RESET
    _write(f"{rule}\n> \n{rule}\n  {GREY}? for shortcuts{RESET}\x1b[2F\x1b[3G")


def prompt(text: str) -> None:
    """Type `text` into the input box, then send it: the box gives way to the user's message."""
    input_box()
    time.sleep(0.5)
    for key in text:
        _write(key)
        time.sleep(KEY_S)
    time.sleep(0.4)
    _write(f"\x1b[1F\x1b[J{GREY}> {text}{RESET}\n\n")


SHOWN: list[dict] = []  # the matches the session last showed


def _table(matches: list[dict]) -> str:
    rows = [("Score", "Title", "Company")] + [
        (f"{m['score']:.2f}", m["title"], m["company"]) for m in matches
    ]
    widths = [max(len(r[i]) for r in rows) for i in range(3)]
    out = ["  " + "  ".join(BOLD + c.ljust(w) + RESET for c, w in zip(rows[0], widths))]
    out += ["  " + "  ".join(c.ljust(w) for c, w in zip(r, widths)) for r in rows[1:]]
    return "\n".join(out)


def whats_new() -> None:
    think()
    summary = call("status_summary")["since_last_review"]
    think(0.6)
    matches = call("list_matches", new_only=True)["matches"]
    SHOWN[:] = matches
    run = summary["last_run"]
    failures = summary["site_failures"]
    say(
        f"**{summary['runs']} run** since your last review: {run['scraped']} postings scraped, "
        f"{run['scored']} scored, **{summary['new_matches']} new matches**. "
        + ("No site failures." if not failures else f"Failed: {', '.join(f['site'] for f in failures)}."),
        _table(matches),
        "Want to look at one, or should I prepare the best?",
    )


def discard() -> None:
    think()
    last = SHOWN[-1]  # "the last one": Claude passes the id from the list it showed
    call("set_status", job_id=last["id"], status="discarded", notes="not my area")
    say(f"Discarded {last['title']} at {last['company']}: not your area.")


def show_one() -> None:
    think()
    job = call("show", job_id="head of finance")
    say(
        f"**{job['title']}** at {job['company']}, {job['location']}: score **{job['score']:.2f}**",
        job["score_reason"],
        f"- Matches: {', '.join(job['matching_skills'])}\n- Missing: {', '.join(job['missing_skills'])}",
    )


def prepare_it() -> None:
    think()
    call("prepare", job_id="head of finance")
    think(0.6)
    materials = call("show", job_id="head of finance")["materials"]
    pages = materials["page_counts"]
    say(
        f"Ready: a **{pages['cv']}-page CV** and a **{pages['cover_letter']}-page cover letter** "
        f"({materials['cover_letter_words']} words).",
        f"- Keywords: {', '.join(materials['keywords'])}\n"
        + "\n".join(f"- {line[0].upper()}{line[1:]}" for line in materials["tailoring"]),
        "\n".join(f"  {_rel(path)}" for path in materials["pdfs"].values()),
        "Want anything tightened before you send it?",
    )


def done() -> None:
    think(0.8)
    call("mark_reviewed")
    say("Marked as reviewed: next time, \"new\" means new since now. Good luck with Globex Energy!")


TURNS = [
    ("What's new?", whats_new),
    ("not the last one, not my area", discard),
    ("show me the Head of Finance one", show_one),
    ("prepare it", prepare_it),
    ("looks good, I'm done", done),
]


def welcome() -> None:
    inner = 46
    rows = [  # (plain text, for the padding; styled text)
        ("✻ Welcome to Claude Code!", f"{ORANGE}✻{RESET} Welcome to {BOLD}Claude Code{RESET}!"),
        ("", ""),
        ("  /help for help", f"  {GREY}/help for help{RESET}"),
        ("", ""),
        ("  cwd: ~/door", f"  {GREY}cwd: ~/door{RESET}"),
    ]
    out = [ORANGE + "╭" + "─" * inner + "╮" + RESET]
    out += [f"{ORANGE}│{RESET} {styled}{' ' * (inner - 1 - len(plain))}{ORANGE}│{RESET}" for plain, styled in rows]
    out.append(ORANGE + "╰" + "─" * inner + "╯" + RESET)
    _write("\n".join(out) + "\n\n")


def seed() -> None:
    """The run a review session follows: the demo boards scraped and scored, unrecorded."""
    pauses = shim.SEARCH_PAUSE_S, shim.SCORE_PAUSE_S
    shim.SEARCH_PAUSE_S = shim.SCORE_PAUSE_S = 0
    result = asyncio.run(tools.find_jobs())
    shim.SEARCH_PAUSE_S, shim.SCORE_PAUSE_S = pauses
    if "error" in result:
        sys.exit(f"claude_session: the seed run failed: {result['error']}")


def main() -> None:
    if sys.argv[1:] == ["--seed"]:
        seed()
        return
    time.sleep(0.3)
    welcome()
    for text, turn in TURNS:
        prompt(text)
        turn()
        time.sleep(READ_S)
    input_box()
    # Hold the last frame like a session waiting for its next prompt, until VHS stops recording.
    time.sleep(60)


if __name__ == "__main__":
    main()
