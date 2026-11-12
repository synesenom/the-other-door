"""Plan how to install The other door's external tools (issue #141).

Pure planning: `detect_platform` names the
OS family and `plan_install(tool, platform)` returns the exact argv that
would install a tool there — nothing here executes anything. `door doctor --fix`
(`_setup_core`) shows the plan, asks, runs it, and re-checks with `doctor`.

Tools (keys match `door.core.doctor` check names via `TOOL_FOR_CHECK`):

    latex       Tectonic everywhere: one ~60 MB binary from its official
                installer into ~/.local/bin, no sudo; it fetches the LaTeX
                packages a document needs on first use
    claude      the `claude` CLI via Anthropic's native installer into
                ~/.local/bin, no sudo, no Node, updates itself (npm only when
                curl is missing and npm is present)

A platform/tool pair with no automated route returns no commands and a
human-readable `hint`.
"""

from __future__ import annotations

import platform as _platform
import os
import shutil
from pathlib import Path

INSTALLABLE = ("latex", "claude")
TOOL_FOR_CHECK = {"latex": "latex", "claude CLI": "claude"}

def _downloaded_then_run(download: str, shell: str) -> str:
    """A POSIX shell line that downloads an install script, then runs it.

    Not `download | shell`: a pipe's status is the shell's, so a failed download runs an
    empty script and passes, and the install looks done while curl's error is lost.
    """
    return f"s=\"$({download})\" && printf '%s\\n' \"$s\" | {shell}"


_CLAUDE_NPM = ["npm", "install", "-g", "@anthropic-ai/claude-code"]
_CLAUDE_SH = _downloaded_then_run("curl -fsSL https://claude.ai/install.sh", "bash -s stable")
_CLAUDE_PS1 = "& ([scriptblock]::Create((irm https://claude.ai/install.ps1))) stable"
_CLAUDE_DOCS = "https://code.claude.com/docs/en/setup"


def detect_platform(system: str | None = None, os_release: str | None = None) -> str:
    """"macos" | "debian" | "fedora" | "arch" | "linux" (another distro) | "windows" | "other"."""
    system = system if system is not None else _platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Windows":
        return "windows"
    if system != "Linux":
        return "other"
    if os_release is None:
        try:
            os_release = Path("/etc/os-release").read_text(encoding="utf-8")
        except OSError:
            os_release = ""
    fields = {}
    for line in os_release.splitlines():
        key, _, value = line.partition("=")
        fields[key.strip()] = value.strip().strip('"').lower()
    ids = [fields.get("ID", "")] + fields.get("ID_LIKE", "").split()
    for family, members in (("debian", {"debian", "ubuntu"}), ("fedora", {"fedora", "rhel", "centos"}), ("arch", {"arch"})):
        if any(i in members for i in ids):
            return family
    return "linux"


_TECTONIC_SH = _downloaded_then_run("curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.fullyjustified.net", "sh")
_TECTONIC_PS1 = "iex ((New-Object System.Net.WebClient).DownloadString('https://drop-ps1.fullyjustified.net'))"
_UNIX = ("macos", "debian", "fedora", "arch", "linux")


def tectonic_dir(home: Path | None = None) -> Path:
    """Where `setup` installs Tectonic: ~/.local/bin (user-owned, no sudo)."""
    return (Path(home) if home is not None else Path.home()) / ".local" / "bin"


def find_tectonic(which=shutil.which, home: Path | None = None) -> str | None:
    """The Tectonic binary: the packaged app's own (`$DOOR_BIN`, #223), else on PATH, else where
    `setup` put it (which may not be on PATH)."""
    bundled = os.environ.get("DOOR_BIN")
    if bundled:
        for name in ("tectonic", "tectonic.exe"):
            candidate = Path(bundled) / name
            if candidate.is_file():
                return str(candidate)
    found = which("tectonic")
    if found:
        return found
    for name in ("tectonic", "tectonic.exe"):
        candidate = tectonic_dir(home) / name
        if candidate.is_file():
            return str(candidate)
    return None


def claude_dir(home: Path | None = None) -> Path:
    """Where Anthropic's native installer puts `claude`: ~/.local/bin (user-owned, no sudo)."""
    return (Path(home) if home is not None else Path.home()) / ".local" / "bin"


def find_claude(which=shutil.which, home: Path | None = None) -> str | None:
    """The `claude` CLI: on PATH, else where the native installer put it (which may not be on PATH)."""
    found = which("claude")
    if found:
        return found
    for name in ("claude", "claude.exe"):
        candidate = claude_dir(home) / name
        if candidate.is_file():
            return str(candidate)
    return None


def plan_install(tool: str, platform: str, *, which=shutil.which, home: Path | None = None) -> dict:
    """The commands that would install `tool` on `platform`.

    Returns:
        ``{"tool", "commands": [argv, ...], "hint": str | None, "note":
        str | None}`` — ``commands`` is empty (with a ``hint``) when there
        is no automated route; ``note`` is what the user must still do
        afterwards.

    Raises:
        ValueError: unknown tool.
    """
    if tool not in INSTALLABLE:
        raise ValueError(f"unknown tool {tool!r} (installable: {', '.join(INSTALLABLE)})")
    commands: list[list[str]] = []
    hint = note = None

    if tool == "latex":
        # Tectonic's official installers drop one binary into the current
        # directory; run them inside ~/.local/bin. The other door finds it there even
        # when that directory is not on PATH (`find_tectonic`).
        bin_dir = tectonic_dir(home)
        note = (
            f"Tectonic is in {bin_dir}; The other door finds it there, so adding that folder to PATH is "
            "optional. The first PDF takes a minute or two while it downloads LaTeX packages."
        )
        if platform in _UNIX:
            if which("curl"):
                commands = [["sh", "-c", f"mkdir -p '{bin_dir}' && cd '{bin_dir}' && {_TECTONIC_SH}"]]
            else:
                hint = "install curl, then re-run setup — or install Tectonic yourself (https://tectonic-typesetting.github.io)"
        elif platform == "windows":
            commands = [[
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                f"New-Item -ItemType Directory -Force -Path '{bin_dir}' | Out-Null; "
                f"Set-Location '{bin_dir}'; {_TECTONIC_PS1}",
            ]]
        else:
            hint = "install Tectonic (https://tectonic-typesetting.github.io) or a TeX distribution with xelatex"

    elif tool == "claude":
        note = (
            "claude goes into ~/.local/bin (no sudo) and updates itself; The other door finds it there even "
            "if that folder is not on PATH. Run `claude` once afterwards to log in with your Pro/Max plan"
        )
        if platform == "windows":
            commands = [["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _CLAUDE_PS1]]
        elif platform in _UNIX:
            if which("curl"):
                commands = [["sh", "-c", _CLAUDE_SH]]
            elif which("npm"):
                commands = [_CLAUDE_NPM]
        if not commands:
            hint = (
                f"install curl, then re-run ./door doctor --fix — or follow {_CLAUDE_DOCS}"
                if platform in _UNIX else f"install the claude CLI: {_CLAUDE_DOCS}"
            )

    return {
        "tool": tool,
        "commands": commands,
        "hint": hint,
        "note": note,
    }


def plan_mcp_registration(
    repo_root: Path, platform: str, *, which=shutil.which, home: Path | None = None,
) -> dict | None:
    """A local-scope `claude mcp add` for the venv's interpreter, when `.mcp.json`'s
    entry cannot start the server here; None when it can.

    `.mcp.json` names `.venv/bin/python`, which a Windows venv does not have
    (it has `.venv\\Scripts\\python.exe`); a local entry with the same name
    takes precedence over the project one. It puts src/ on PYTHONPATH as the
    project entry does (the package is src/door/, never installed). ``cleanup`` removes a stale local
    entry first (its failure is fine).
    """
    from door.core.doctor import mcp_interpreter, mcp_server_argv

    if platform != "windows":
        return None
    os_name = "win32"
    argv = mcp_server_argv(repo_root, os_name)
    from door.core import workspace

    home_env = [] if workspace.HOME == workspace.REPO_ROOT else ["-e", f"DOOR_HOME={workspace.HOME}"]
    if Path(argv[0]).resolve() != mcp_interpreter(repo_root, os_name).resolve():
        return None  # .mcp.json's own interpreter exists
    claude = find_claude(which, home)
    if not claude:
        return {"tool": "mcp", "commands": [], "cleanup": [], "hint": "install the claude CLI, then re-run setup", "note": None}
    return {
        "tool": "mcp",
        "commands": [[claude, "mcp", "add", "--scope", "local", "door", "-e", f"PYTHONPATH={Path(repo_root) / 'src'}", *home_env, "--", *argv]],
        "cleanup": [claude, "mcp", "remove", "--scope", "local", "door"],
        "hint": None,
        "note": None,
    }
