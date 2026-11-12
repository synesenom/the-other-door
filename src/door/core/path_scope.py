"""Where an MCP tool may read or write a local file the caller names (#441): inside the data
folder (`workspace.HOME`) or the checkout, nowhere else. A conversation steered by a job ad
must not be able to point `draft_cv` at `~/.ssh` or `export_data` at another folder.

The desktop app sets `ENV` when it starts the server: there every path comes from a file
dialog the main process runs (the window may never name one, `app/src/main/ipc.ts`
`PATH_ARGS`). The CLI does not go through here: a path typed in a shell is the user's own.
"""

from __future__ import annotations

import os
from pathlib import Path

from door.core import workspace

ENV = "DOOR_PATHS_FROM_DIALOGS"


def check(path: str) -> Path:
    """`path` (relative ones from the data folder), resolved, if a tool may use it.

    Raises:
        ValueError: it lies outside the data folder and the checkout.
    """
    given = Path(path).expanduser()
    full = given if given.is_absolute() else workspace.HOME / given
    if os.environ.get(ENV) == "1":
        return full
    real = full.resolve()
    if any(real.is_relative_to(Path(root).resolve()) for root in (workspace.HOME, workspace.REPO_ROOT)):
        return full
    raise ValueError(
        f"{path} is outside the data folder ({workspace.HOME}); copy the file into it "
        "(e.g. the profile folder) and name it there"
    )
