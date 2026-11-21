"""Evidence for /dev-correct: the typed user turns of Claude Code transcripts, and a check of quoted corrections.

Standard library only. `extract <dir>` prints the turns as JSON; `verify <classes.json> <turns.json>` prints the
classes with the quotes that are not verbatim in a turn dropped and their distinct sessions counted.
"""

import json
import sys
from pathlib import Path

MIN_SESSIONS = 2
BEFORE_CHARS = 300  # the end of Claude's answer is what a correction answers


def _text_of(content):
    """The typed text of a message's content, or None when it holds none (tool results)."""
    if isinstance(content, str):
        return content
    parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(parts) if parts else None


def turns(paths):
    """Typed user turns of the given jsonl files, each with `text`, `before`, `session`, `at`, `file`."""
    found = []
    for path in map(Path, paths):
        before = ""
        for raw in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            content = (entry.get("message") or {}).get("content")
            if content is None:
                continue
            if entry.get("type") == "assistant":
                if entry.get("isSidechain"):
                    continue
                text = _text_of(content) if isinstance(content, list) else None
                if text and text.strip():
                    before = text
                continue
            if entry.get("type") != "user":
                continue
            if entry.get("isCompactSummary") or entry.get("isMeta") or entry.get("isSidechain"):
                continue
            text = _text_of(content)
            if not text or not text.strip() or text.startswith(("<", "[Request interrupted")):
                continue
            found.append(
                {
                    "text": text,
                    "before": before[-BEFORE_CHARS:],
                    "session": entry.get("sessionId"),
                    "at": entry.get("timestamp"),
                    "file": path.name,
                }
            )
    return found


def verify(classes, all_turns):
    """Keep only quotes that are a substring of a turn; `sessions` counts the distinct sessions they come from."""
    checked = []
    for cls in classes:
        quotes, sessions = [], set()
        for quote in cls.get("quotes", []):
            hits = {t["session"] for t in all_turns if quote and quote in t["text"]}
            if hits and quote not in quotes:
                quotes.append(quote)
            sessions |= hits
        checked.append({**cls, "quotes": quotes, "sessions": len(sessions), "qualifies": len(sessions) >= MIN_SESSIONS})
    return checked


def main(argv):
    if len(argv) == 3 and argv[1] == "extract":
        json.dump(turns(sorted(Path(argv[2]).glob("*.jsonl"))), sys.stdout, ensure_ascii=False)
        return 0
    if len(argv) == 4 and argv[1] == "verify":
        classes = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        all_turns = json.loads(Path(argv[3]).read_text(encoding="utf-8"))
        json.dump(verify(classes, all_turns), sys.stdout, ensure_ascii=False, indent=2)
        return 0
    print("usage: correct_evidence.py extract <dir> | verify <classes.json> <turns.json>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
