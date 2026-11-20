"""Guard: user state is written through `utils.write_atomic`, never in place (#363).

A write that fails part-way (a full disk, a kill) must leave the old file whole. So under `src/door/`
no `.write_text(`, `.write_bytes(`, `open(..., "w"|"wb"|"x")` or `shutil.copy*` outside `core/utils.py`,
unless the writer is named in EXEMPT, by (file, function), with the reason it is atomic by construction
or not user state.
"""

import ast

from paths import REPO_ROOT

_STAGED = "writes into a staging or work folder that is moved in whole"
_DOWNLOAD = "a download into a temporary destination the caller checks and moves"

EXEMPT = {
    ("core/migrations.py", "write_version"): "a temp file linked or replaced into place (link semantics)",
    ("core/migrations.py", "_backup"): "copies the folder to a new backup folder, which is not state in use",
    ("core/migrations.py", "_restore"): "puts a backup back over a folder a failed step left; there is no older file to keep",
    ("core/phone/phone.py", "install_cloudflared"): _STAGED,
    ("core/phone/launch_agent.py", "install"): "a launch-agent plist outside HOME, not user state",
    ("core/sync/archive.py", "_keep_local_keys"): _STAGED,
    ("core/sync/drive.py", "download"): _DOWNLOAD,
    ("core/downloads/pinned.py", "http_get"): _DOWNLOAD,
    ("render/html_pdf.py", "_launch"): "the browser's stderr log in its own fresh profile folder",
}

_COPIERS = {"copy", "copy2", "copyfile", "copyfileobj", "copytree"}


def _is_write(node: ast.Call) -> bool:
    f = node.func
    if isinstance(f, ast.Attribute):
        if f.attr in ("write_text", "write_bytes"):
            return True
        if isinstance(f.value, ast.Name) and f.value.id == "shutil" and f.attr in _COPIERS:
            return True
    name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
    if name == "open":
        mode = None
        for k in node.keywords:
            if k.arg == "mode":
                mode = k.value
        position = 0 if isinstance(f, ast.Attribute) else 1
        if mode is None and len(node.args) > position:
            mode = node.args[position]
        return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and mode.value[:1] in ("w", "x")
    return False


def _functions(tree):
    """Yield (call, enclosing function name or None) for every call."""

    def walk(node, name):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield from walk(child, child.name)
            else:
                if isinstance(child, ast.Call):
                    yield child, name
                yield from walk(child, name)

    yield from walk(tree, None)


def _bare_writers() -> list[str]:
    found = []
    root = REPO_ROOT / "src" / "door"
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel == "core/utils.py":
            continue
        for node, func in _functions(ast.parse(path.read_text(encoding="utf-8"))):
            if _is_write(node) and (rel, func) not in EXEMPT and (rel, None) not in EXEMPT:
                found.append(f"{rel}:{node.lineno} in {func}")
    return found


def test_no_user_state_is_written_in_place():
    assert _bare_writers() == []


def test_every_exemption_still_names_a_writer():
    root = REPO_ROOT / "src" / "door"
    used = set()
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        for node, func in _functions(ast.parse(path.read_text(encoding="utf-8"))):
            if _is_write(node):
                used.update({(rel, func), (rel, None)})
    assert [k for k in EXEMPT if k not in used] == []
