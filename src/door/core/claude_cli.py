"""The environment every `claude` subprocess runs in: which Claude plan pays for it.

`claude` reads its login from `CLAUDE_CONFIG_DIR` (default `~/.claude`). A shell
alias such as `claude-personal` (`CLAUDE_CONFIG_DIR=~/.claude-personal claude`)
does not exist for a subprocess, so profile/config.json's `claude_config_dir`
names the directory and every call site passes `env()` — the same plan whether
The other door runs from a conversation, a terminal or cron.
"""

import json
import os
import subprocess
from pathlib import Path

from door.core import installers, usage, workspace


def config_dir(profile_dir: Path | None = None) -> str | None:
    """profile/config.json's `claude_config_dir`, `~` expanded; None when unset.

    Reads the raw JSON rather than validating the whole config: a broken
    config is reported by the command that loads it, never by this lookup.
    """
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR
    try:
        value = json.loads((Path(profile_dir) / "config.json").read_text(encoding="utf-8")).get("claude_config_dir")
    except (OSError, ValueError, AttributeError):
        return None
    return str(Path(value).expanduser()) if value else None


def env(base: dict[str, str] | None = None, profile_dir: Path | None = None) -> dict[str, str]:
    """The environment a `claude` subprocess runs in: a copy of `base` (default:
    this process's environment without its `CLAUDE_CODE_*`/`CLAUDECODE`
    variables, so a call made from inside a Claude Code session gets a session
    of its own instead of attaching to the parent's) with `CLAUDE_CONFIG_DIR`
    set from the profile — the configured plan wins over an inherited one.
    Unchanged when the profile names none."""
    if base is None:
        base = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_") and k != "CLAUDECODE"}
    result = dict(base)
    configured = config_dir(profile_dir)
    if configured:
        result["CLAUDE_CONFIG_DIR"] = configured
    return result


# How every `claude -p` call asks for its answer (#575): a stream of JSON lines, whose last
# `result` line is the envelope `--output-format json` gives and whose `rate_limit_event`
# says how full the plan's windows are. `-p` refuses `stream-json` without `--verbose`.
STREAM_ARGS = ["--output-format", "stream-json", "--verbose"]

# The plan windows read from a `rate_limit_event` (`unifiedWindows` or `rateLimitType`).
WINDOWS = ("five_hour", "seven_day")


def _fraction(value) -> float | None:
    """A utilization as a 0-1 fraction: `claude` reports one (0.09), but a figure above 1
    is read as a percent (42 -> 0.42), clamped to 0-1."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value > 1:
        value = value / 100
    return round(min(1.0, max(0.0, float(value))), 4)


def _window(utilization, resets_at, status) -> dict:
    window = {}
    used = _fraction(utilization)
    if used is not None:
        window["used"] = used
    if isinstance(resets_at, (int, float)) and not isinstance(resets_at, bool):
        window["resets_at"] = int(resets_at)
    if window and isinstance(status, str):
        window["status"] = status
    return window


def _limits(info) -> dict | None:
    """`{"status"?, "five_hour"?: {"used"?, "resets_at"?, "status"?}, "seven_day"?: {...}}`
    from a `rate_limit_info`, or None when it says nothing usable. `unifiedWindows` is preferred;
    without it the top-level `utilization`/`resetsAt` belong to the window `rateLimitType` names."""
    if not isinstance(info, dict):
        return None
    limits = {}
    unified = info.get("unifiedWindows")
    if isinstance(unified, dict) and any(isinstance(unified.get(w), dict) for w in WINDOWS):
        for name in WINDOWS:
            raw = unified.get(name)
            if isinstance(raw, dict) and (window := _window(raw.get("utilization"), raw.get("resetsAt"), raw.get("status"))):
                limits[name] = window
    elif info.get("rateLimitType") in WINDOWS:
        window = _window(info.get("utilization"), info.get("resetsAt"), None)
        if window:
            limits[info["rateLimitType"]] = window
    if not limits:
        return None
    if isinstance(info.get("status"), str):
        limits = {"status": info["status"], **limits}
    return limits


def read_stream(stdout: str | None) -> tuple[str | None, dict | None]:
    """The envelope and the plan's limits of a `--output-format stream-json --verbose` call.

    `envelope` is the last `{"type": "result", ...}` line, re-serialised, so `envelope_result`,
    `json_result` and `usage.weight` read it as they read a `--output-format json` answer;
    `limits` comes from the call's last `rate_limit_event` (`_limits`). A `stdout` that is one
    result object (a plain `--output-format json` envelope, whatever its line breaks) is
    returned as it is, with no limits; one with no `result`
    line has no envelope. Never raises: a garbled line is skipped.
    """
    text = stdout or ""
    try:
        whole = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        whole = None
    if isinstance(whole, dict) and whole.get("type") in (None, "result"):
        return text, None
    envelope = limits = None
    for line in text.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        if message.get("type") == "result":
            envelope = message
        elif message.get("type") == "rate_limit_event":
            limits = _limits(message.get("rate_limit_info"))
    return (json.dumps(envelope) if envelope is not None else None), limits


class ClaudeError(RuntimeError):
    """A `claude -p` call failed: no `claude` binary, a timeout, a non-zero exit,
    or an answer that is not what was asked for."""


def run(
    args: list[str],
    *,
    feature: str,
    input: str | None = None,
    timeout_s: float | None = None,
    profile_dir: Path | None = None,
    cwd: Path | None = None,
) -> str:
    """Run `claude -p <args>` from the repo root (or `cwd`) and return its answer.

    The one way a command talks to the model: print mode on the user's
    Pro/Max plan, the plan the profile names (`env()`), never an API key.
    `feature` (a key of `usage.FEATURES`) names what the call is for: when `args` ask for
    the stream (`STREAM_ARGS`), its result envelope is returned instead of the whole
    stream (`read_stream`) and its weight recorded under `feature` (`usage.record`), a
    failed call's too when it reported one. Output that is no stream is returned as it is.

    Raises:
        ClaudeError: the binary could not be started, the call timed out, or
            it exited non-zero (the message carries `claude`'s stderr).
    """
    argv = [installers.find_claude() or "claude", "-p", *args]
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, cwd=cwd or workspace.REPO_ROOT,
            timeout=timeout_s, env=env(profile_dir=profile_dir),
            # never the server's stdin (tests/core/test_subprocess_stdin_guard_unit.py): the input, else nothing
            input=input, stdin=None if input is not None else subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        raise ClaudeError(f"claude -p timed out after {timeout_s:.0f}s") from None
    except OSError as exc:
        raise ClaudeError(f"could not invoke `claude` CLI: {exc}") from None
    envelope, limits = read_stream(result.stdout)
    usage.record(feature, envelope, limits=limits)  # a failed call drew on the plan too
    if result.returncode != 0:
        detail = (result.stderr or "").strip() or f"exit code {result.returncode}"
        raise ClaudeError(f"claude exited {result.returncode}: {detail}")
    return envelope if envelope is not None else result.stdout


def envelope_result(stdout: str):
    """The `result` of a `--output-format json` envelope: the answer text, or
    the structured answer when the CLI already decoded it.

    Raises:
        ClaudeError: no envelope, or an `is_error` envelope.
    """
    try:
        envelope = json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ClaudeError(f"claude returned no JSON envelope: {exc}") from None
    if not isinstance(envelope, dict):
        raise ClaudeError("claude returned no JSON envelope")
    if envelope.get("is_error"):
        raise ClaudeError(f"claude reported an error: {envelope.get('result')!r}")
    return envelope.get("result")


def json_result(stdout: str):
    """The answer of a `--output-format json` call made with `--json-schema`,
    parsed.

    Raises:
        ClaudeError: no envelope, an `is_error` envelope, or a `result` that
            is not JSON.
    """
    result = envelope_result(stdout)
    if isinstance(result, (dict, list)):
        return result
    try:
        return json.loads(result)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ClaudeError(f"claude's answer is not JSON: {exc}") from None


def ask(
    system_prompt: str,
    input: str,
    *,
    model: str,
    feature: str,
    schema: dict | None = None,
    allowed_tools: tuple[str, ...] = (),
    timeout_s: float | None = None,
    profile_dir: Path | None = None,
):
    """One question to the model: `system_prompt` as the system prompt, `input`
    on stdin, no tools unless `allowed_tools` names some, no session kept.

    With `schema`, the answer is asked for as JSON of that shape and returned
    as a dict; without, the answer text is returned stripped. Either way the
    answer comes as a stream (`STREAM_ARGS`) whose envelope `run()` returns
    and whose weight it records under `feature`.

    Raises:
        ClaudeError: as `run()`, or an answer that is not a JSON object when a
            schema was given.
    """
    args = ["--model", model, "--system-prompt", system_prompt]
    if schema is not None:
        args += ["--json-schema", json.dumps(schema)]
    args += STREAM_ARGS
    args += ["--allowedTools", ",".join(allowed_tools)] if allowed_tools else ["--tools", ""]
    args.append("--no-session-persistence")
    stdout = run(args, feature=feature, input=input, timeout_s=timeout_s, profile_dir=profile_dir)
    if schema is None:
        text = envelope_result(stdout)
        if not isinstance(text, str):
            raise ClaudeError("claude's answer is not text")
        return text.strip()
    answer = json_result(stdout)
    if not isinstance(answer, dict):
        raise ClaudeError("claude's answer is not a JSON object")
    return answer
