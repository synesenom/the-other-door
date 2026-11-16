"""Start the real door MCP server inside a test world: everything is door's own code except the
edges that would leave the computer, which answer from the world the test built.

The journeys (app/journeys/) point DOOR_PYTHON at a wrapper that runs this file instead of
`python -m door.mcp_server`; the install test (app/e2e-install/redirect.ts) has an installed app run it on its
bundled Python and door. No production code knows about it. What it replaces:

- the network: every socket to a host that is not this computer is refused, and `requests`
  answers from `world.json`'s `internet` (a URL -> page map) or fails as an offline host would;
- the job boards `search` reads: one module per board in `world.json`'s `boards`, returning
  those postings (the ads a run finds);
- `follow`'s feed detection and `collect`'s feeds: `world.json`'s `feeds` (company -> platform,
  entry, postings);
- Google Drive: a folder in the world plays the Drive account (`drive/`), and the real sync
  logic (pull, push, conflict) runs over it;
- the phone server: a pretend tunnel with a fixed address;
- faults: before every tool call `faults.json` is read again, so a test can make a named tool
  answer `{"error": ...}`, wait, or kill the server, at the moment it wants.

`claude` is a stand-in first on PATH (claude.py), so the model boundary is a process, as it is for real; the
Chromium print is replaced in this process (print_standin.py, by edges.py). Every tool call is logged to `calls.jsonl`.
"""

import asyncio
import functools
import inspect
import json
import os
import sys
import time
from pathlib import Path

WORLD = Path(sys.argv[1]).resolve()
os.environ["DOOR_WORLD"] = str(WORLD)

# Every thread's stack, written again every 20 s: a test that finds the server stuck names where (#18). Read with
# sys._current_frames on a Python thread, under the GIL: faulthandler.dump_traceback_later's watchdog walks the
# threads without it and can crash the server when a thread starts or ends mid-walk, with no traceback (#98).
import faulthandler  # noqa: E402
import threading  # noqa: E402
import traceback  # noqa: E402

faulthandler.enable()  # a native crash says so on stderr, which the app's problem log keeps


def _write_stacks() -> None:
    frames = sys._current_frames()
    me = threading.get_ident()
    blocks = []
    for ident, frame in frames.items():
        head = f"{'Current thread' if ident == me else 'Thread'} 0x{ident:016x} (most recent call first):\n"
        blocks.append(head + "".join(reversed(traceback.format_stack(frame))))
    (WORLD / "server-stacks.txt").write_text("\n".join(blocks), encoding="utf-8")


def _stacks_every(seconds: float) -> None:
    while True:
        time.sleep(seconds)
        try:
            _write_stacks()
        except OSError:
            pass  # the world may be gone at the end of a test


threading.Thread(target=_stacks_every, args=(20,), daemon=True, name="world-stacks").start()
REPO = Path(__file__).resolve().parents[3]
# The door it runs is the one the app put on PYTHONPATH: the checkout's src/, or an installed app's own
# bundled door (the install test, app/e2e-install/); the checkout's only when nothing is named.
if not os.environ.get("PYTHONPATH"):
    sys.path.insert(0, str(REPO / "src"))

import edges  # noqa: E402,F401 — installs every edge
from edges import log_call, faults  # noqa: E402

# --------------------------------------------------------------------------- the server, with faults and a call log
from door import mcp_server  # noqa: E402


def _fault_for(tool: str) -> dict | None:
    said = faults().get("tools", {}).get(tool)
    if not said:
        return None
    if said.get("once"):
        current = faults()
        current["tools"].pop(tool, None)
        (WORLD / "faults.json").write_text(json.dumps(current), encoding="utf-8")
    return said


def _answer_fault(said: dict):
    if said.get("crash"):
        os._exit(3)
    if "error" in said:
        return {"error": said["error"]}
    return None


def _with_faults(name: str, fn):
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            log_call("tool", tool=name, args={k: v for k, v in kwargs.items() if k != "ctx"})
            said = _fault_for(name)
            if said:
                await asyncio.sleep(said.get("delay_s", 0))
                answer = _answer_fault(said)
                if answer is not None:
                    return answer
            return await fn(*args, **kwargs)

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        log_call("tool", tool=name, args=kwargs)
        said = _fault_for(name)
        if said:
            time.sleep(said.get("delay_s", 0))
            answer = _answer_fault(said)
            if answer is not None:
                return answer
        return fn(*args, **kwargs)

    return wrapper


for _name, _tool in mcp_server.mcp._tool_manager._tools.items():
    _tool.fn = _with_faults(_name, _tool.fn)

if __name__ == "__main__":
    mcp_server.main()
