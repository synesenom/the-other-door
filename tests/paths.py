"""Fixed locations for tests, so a test file's depth under tests/ doesn't matter."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"            # on sys.path: `import door` finds SRC_DIR / "door"
PACKAGE_DIR = SRC_DIR / "door"
TESTS_DIR = REPO_ROOT / "tests"
GOLDEN_DIR = TESTS_DIR / "matching" / "fixtures" / "golden"
# The profile the golden postings are labelled against (a data scientist, like the ads).
GOLDEN_PROFILE_DIR = TESTS_DIR / "matching" / "fixtures" / "golden_profile"
