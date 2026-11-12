"""app/scripts/lock_requirements.py: the packaged app's Python packages, from poetry.lock, pinned by hash (#223)."""

import importlib.util

from paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("lock_requirements", REPO_ROOT / "app" / "scripts" / "lock_requirements.py")
lock_requirements = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lock_requirements)

LOCK = """
[[package]]
name = "requests"
version = "2.32.5"
optional = false
groups = ["main"]
files = [
    {file = "requests-2.32.5-py3-none-any.whl", hash = "sha256:aaa"},
    {file = "requests-2.32.5.tar.gz", hash = "sha256:bbb"},
]

[[package]]
name = "colorama"
version = "0.4.6"
optional = false
groups = ["main"]
markers = "platform_system == \\"Windows\\""
files = [{file = "colorama-0.4.6-py2.py3-none-any.whl", hash = "sha256:ccc"}]

[[package]]
name = "exceptiongroup"
version = "1.3.0"
optional = false
groups = ["main", "dev"]
markers = {main = "python_version < \\"3.11\\"", dev = "python_version < \\"3.13\\""}
files = [{file = "exceptiongroup-1.3.0-py3-none-any.whl", hash = "sha256:eee"}]

[[package]]
name = "pytest"
version = "9.0.3"
optional = false
groups = ["dev"]
files = [{file = "pytest-9.0.3-py3-none-any.whl", hash = "sha256:ddd"}]
"""


def test_the_main_group_pinned_by_every_hash_with_its_marker(tmp_path):
    lock = tmp_path / "poetry.lock"
    lock.write_text(LOCK)
    lines = lock_requirements.requirements(lock)
    assert lines == [
        'colorama==0.4.6 ; platform_system == "Windows" --hash=sha256:ccc',
        'exceptiongroup==1.3.0 ; python_version < "3.11" --hash=sha256:eee',
        "requests==2.32.5 --hash=sha256:aaa --hash=sha256:bbb",
    ]


def test_the_real_lock_has_the_runtime_packages_and_no_test_tools():
    names = {line.split("==")[0] for line in lock_requirements.requirements(REPO_ROOT / "poetry.lock")}
    for wanted in ("pypdfium2", "mcp", "pydantic", "click", "quickjs", "py3langid"):
        assert wanted in names
    for unwanted in ("pytest", "responses", "genbadge"):
        assert unwanted not in names
    assert all("--hash=sha256:" in line for line in lock_requirements.requirements(REPO_ROOT / "poetry.lock"))
