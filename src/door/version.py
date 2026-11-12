"""door's version, one number with the desktop app's (#224): `pyproject.toml` and `app/package.json` say the
same, a test checks, and `scripts/set_version.py X.Y.Z` changes all three. Read here because a packaged app
carries `src/` but no `pyproject.toml`; the MCP server reports it in `initialize`."""

VERSION = "0.1.0"
