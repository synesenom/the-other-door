"""Unit tests for `door.core.installers` (issue #141).

Pure planning: which platform we are on, and the exact argv that would
install each tool there. Nothing is ever executed here.
"""

import subprocess

import pytest

from door.core import installers
from door.core.installers import detect_platform, find_tectonic, plan_install


@pytest.fixture(autouse=True)
def _never_execute(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("installers must only plan, never execute")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)


# --------------------------------------------------------------------------- #
# detect_platform
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("os_release,expected", [
    ('ID=pop\nID_LIKE="ubuntu debian"\n', "debian"),
    ('ID="rhel"\nID_LIKE="fedora"\n', "fedora"),
    ("ID=arch\n", "arch"),
    ("ID=alpine\n", "linux"),
])
def test_detect_platform_linux_from_os_release(os_release, expected):
    assert detect_platform("Linux", os_release) == expected


def test_detect_platform_macos_and_windows():
    assert detect_platform("Darwin", "") == "macos"
    assert detect_platform("Windows", "") == "windows"
    assert detect_platform("FreeBSD", "") == "other"


# --------------------------------------------------------------------------- #
# plan_install
# --------------------------------------------------------------------------- #

def _which(*present):
    return lambda name: f"/usr/bin/{name}" if name in present else None


TECTONIC_SH = "s=\"$(curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.fullyjustified.net)\" && printf '%s\\n' \"$s\" | sh"


@pytest.mark.parametrize("platform", ["macos", "linux"])
def test_plan_latex_is_tectonic_into_local_bin_without_sudo(platform, tmp_path):
    plan = plan_install("latex", platform, which=_which("curl"), home=tmp_path)
    [argv] = plan["commands"]
    assert argv[:2] == ["sh", "-c"]
    bin_dir = tmp_path / ".local" / "bin"
    assert argv[2] == f"mkdir -p '{bin_dir}' && cd '{bin_dir}' && {TECTONIC_SH}"
    assert "sudo" not in " ".join(argv)
    assert plan["hint"] is None
    assert "PATH is optional" in plan["note"]


def test_plan_latex_on_windows_uses_the_powershell_installer(tmp_path):
    plan = plan_install("latex", "windows", which=_which(), home=tmp_path)
    [argv] = plan["commands"]
    assert argv[:4] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"]
    assert str(tmp_path / ".local" / "bin") in argv[-1]
    assert "https://drop-ps1.fullyjustified.net" in argv[-1]


def test_plan_latex_without_curl_is_a_hint(tmp_path):
    plan = plan_install("latex", "debian", which=_which(), home=tmp_path)
    assert plan["commands"] == []
    assert "curl" in plan["hint"]


def test_plan_latex_on_an_unknown_os_is_a_hint(tmp_path):
    plan = plan_install("latex", "other", which=_which("curl"), home=tmp_path)
    assert plan["commands"] == []
    assert "tectonic" in plan["hint"].lower()


def test_find_tectonic_prefers_path(tmp_path):
    assert find_tectonic(which=_which("tectonic"), home=tmp_path) == "/usr/bin/tectonic"


def test_find_tectonic_falls_back_to_local_bin(tmp_path):
    assert find_tectonic(which=_which(), home=tmp_path) is None
    binary = tmp_path / ".local" / "bin" / "tectonic"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    assert find_tectonic(which=_which(), home=tmp_path) == str(binary)


def test_find_tectonic_takes_the_bundled_one_first(tmp_path, monkeypatch):
    # A packaged app ships its own Tectonic and names its folder in DOOR_BIN (#223).
    bundled = tmp_path / "bundle" / "bin" / "tectonic"
    bundled.parent.mkdir(parents=True)
    bundled.write_text("")
    monkeypatch.setenv("DOOR_BIN", str(bundled.parent))
    assert find_tectonic(which=_which("tectonic"), home=tmp_path) == str(bundled)
    monkeypatch.setenv("DOOR_BIN", str(tmp_path / "nowhere"))
    assert find_tectonic(which=_which("tectonic"), home=tmp_path) == "/usr/bin/tectonic"


_NATIVE_SH = [["sh", "-c", "s=\"$(curl -fsSL https://claude.ai/install.sh)\" && printf '%s\\n' \"$s\" | bash -s stable"]]
_NATIVE_PS1 = [[
    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
    "& ([scriptblock]::Create((irm https://claude.ai/install.ps1))) stable",
]]


def test_claude_dir_and_find_claude(tmp_path):
    assert installers.claude_dir(tmp_path) == tmp_path / ".local" / "bin"
    assert installers.find_claude(which=lambda n: None, home=tmp_path) is None
    binary = tmp_path / ".local" / "bin" / "claude"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    assert installers.find_claude(which=lambda n: None, home=tmp_path) == str(binary)
    assert installers.find_claude(which=lambda n: "/usr/bin/claude", home=tmp_path) == "/usr/bin/claude"


def test_find_claude_exe(tmp_path):
    binary = tmp_path / ".local" / "bin" / "claude.exe"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    assert installers.find_claude(which=lambda n: None, home=tmp_path) == str(binary)


@pytest.mark.parametrize("platform", ["macos", "debian", "fedora", "arch", "linux"])
def test_plan_claude_native_installer_on_unix(platform):
    plan = plan_install("claude", platform, which=_which("curl"))
    assert plan["commands"] == _NATIVE_SH
    assert "~/.local/bin" in plan["note"] and "sudo" in plan["note"] and "update" in plan["note"]
    assert "log in" in plan["note"]


def test_plan_claude_native_installer_on_windows():
    assert plan_install("claude", "windows", which=_which())["commands"] == _NATIVE_PS1


@pytest.mark.parametrize("platform", ["macos", "debian", "windows"])
def test_plan_claude_default_has_no_npm_node_or_sudo(platform):
    plan = plan_install("claude", platform, which=_which("curl", "npm", "node", "brew", "winget"))
    flat = " ".join(a for argv in plan["commands"] for a in argv)
    assert "npm" not in flat and "node" not in flat.lower() and "sudo" not in flat


def test_plan_claude_without_curl_falls_back_to_npm():
    plan = plan_install("claude", "debian", which=_which("npm"))
    assert plan["commands"] == [["npm", "install", "-g", "@anthropic-ai/claude-code"]]


def test_plan_claude_without_curl_or_npm_is_a_hint():
    plan = plan_install("claude", "debian", which=_which())
    assert plan["commands"] == []
    for text in ("install curl", "./door doctor --fix", "https://code.claude.com/docs/en/setup"):
        assert text in plan["hint"]
    assert "Node" not in plan["hint"] and "nodejs.org" not in plan["hint"]


def test_plan_claude_on_unknown_platform_is_a_hint():
    plan = plan_install("claude", "other", which=_which("curl", "npm"))
    assert plan["commands"] == []
    assert "https://code.claude.com/docs/en/setup" in plan["hint"]


def test_plan_unknown_tool():
    with pytest.raises(ValueError, match="unknown tool"):
        plan_install("emacs", "debian", which=_which())


@pytest.mark.parametrize("tool", ["latex", "claude"])
@pytest.mark.parametrize("platform", ["macos", "debian", "fedora", "windows"])
def test_no_plan_uses_sudo(tool, platform):
    plan = plan_install(tool, platform, which=_which("curl", "npm", "brew"))
    assert all("sudo" not in argv for argv in plan["commands"])


def test_doctor_check_names_map_to_tools():
    assert installers.TOOL_FOR_CHECK == {
        "latex": "latex",
        "claude CLI": "claude",
    }


def _mcp_repo(tmp_path, command):
    (tmp_path / ".mcp.json").write_text(
        '{"mcpServers": {"door": {"command": "%s", "args": ["-m", "door.mcp_server"]}}}' % command
    )
    return tmp_path


def test_mcp_registration_not_needed_outside_windows(tmp_path):
    repo = _mcp_repo(tmp_path, ".venv/bin/python")
    for platform in ("macos", "debian", "linux"):
        assert installers.plan_mcp_registration(repo, platform, which=lambda n: "/bin/claude") is None


def test_mcp_registration_not_needed_when_mcp_json_interpreter_exists_on_windows(tmp_path):
    repo = _mcp_repo(tmp_path, ".venv/bin/python")
    (repo / ".venv" / "bin").mkdir(parents=True)
    (repo / ".venv" / "bin" / "python").write_text("")
    assert installers.plan_mcp_registration(repo, "windows", which=lambda n: "C:/claude") is None


def test_mcp_registration_without_claude_is_a_hint(tmp_path):
    step = installers.plan_mcp_registration(_mcp_repo(tmp_path, ".venv/bin/python"), "windows", which=lambda n: None)
    assert step["commands"] == [] and "claude" in step["hint"]


def test_mcp_registration_uses_claude_from_local_bin_off_path(tmp_path):
    binary = tmp_path / ".local" / "bin" / "claude.exe"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    (tmp_path / "repo").mkdir()
    repo = _mcp_repo(tmp_path / "repo", ".venv/bin/python")
    step = installers.plan_mcp_registration(repo, "windows", which=lambda n: None, home=tmp_path)
    assert step["commands"][0][0] == str(binary)


def test_mcp_registration_without_claude_anywhere_says_install_it(tmp_path):
    (tmp_path / "repo").mkdir()
    repo = _mcp_repo(tmp_path / "repo", ".venv/bin/python")
    step = installers.plan_mcp_registration(repo, "windows", which=lambda n: None, home=tmp_path)
    assert step["commands"] == [] and "install the claude CLI, then re-run setup" in step["hint"]
