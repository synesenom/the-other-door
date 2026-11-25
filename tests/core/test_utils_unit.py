"""Unit tests for utils.py helpers: _escape_html, _normalize_text_for_ats, and _validate_job_id."""

import pytest

from door.core.utils import _escape_html, _normalize_text_for_ats, _validate_job_id


# --------------------------------------------------------------------------- #
# _escape_html
# --------------------------------------------------------------------------- #

class TestEscapeHtml:
    def test_clean_string_unchanged(self):
        assert _escape_html("Hello World") == "Hello World"

    def test_markup_and_quotes_become_text(self):
        assert _escape_html("R&D <Lead> \"x\" 'y'") == "R&amp;D &lt;Lead&gt; &quot;x&quot; &#x27;y&#x27;"

    def test_it_is_not_escaped_twice_by_itself(self):
        assert _escape_html("&amp;") == "&amp;amp;"


# --------------------------------------------------------------------------- #
# _normalize_text_for_ats
# --------------------------------------------------------------------------- #

class TestNormalizeTextForAts:
    def test_dashes(self):
        assert _normalize_text_for_ats("foo—bar") == "foo - bar"
        assert _normalize_text_for_ats("–") == "-"

    def test_smart_quotes(self):
        assert _normalize_text_for_ats("“hello”") == '"hello"'
        assert _normalize_text_for_ats("‘it’s") == "'it's"

    def test_zero_width_chars(self):
        # Each zero-width character should be removed entirely
        assert _normalize_text_for_ats("a​b‌c‍d﻿e") == "abcde"

    def test_ligatures(self):
        assert _normalize_text_for_ats("ﬀ ﬁ ﬂ ﬃ ﬄ") == "ff fi fl ffi ffl"

    def test_clean_string_unchanged(self):
        assert _normalize_text_for_ats("Hello World") == "Hello World"


# --------------------------------------------------------------------------- #
# _validate_job_id
# --------------------------------------------------------------------------- #

class TestValidateJobId:
    def test_slug_with_hex_suffix_accepted(self):
        # make_job_id appends -<6-char-hex> for disambiguation; should not raise
        _validate_job_id("jobindex.acme.data-scientist-a1b2c3")

    def test_a_single_dash_only_segment_is_accepted(self):
        # A segment without dots is a valid id.
        _validate_job_id("jobindex-acme-data-scientist")

    def test_a_site_name_with_an_underscore_is_accepted(self):
        # career_sites is a site, and its ids start with it.
        _validate_job_id("career_sites.gartner.lead-data-scientist")

    @pytest.mark.parametrize(
        "job_id",
        ["../evil", "foo/../bar", "/etc/passwd", "MyJob", "_foo", "a._b", "", "-foo",
         "..", "a..b", ".hidden", "trailing.", "a.-b"],
    )
    def test_rejected(self, job_id):
        with pytest.raises(ValueError, match="invalid job_id"):
            _validate_job_id(job_id)


# --------------------------------------------------------------------------- #
# write_json_atomic
# --------------------------------------------------------------------------- #

class TestWriteJsonAtomic:
    def test_writes_json_and_creates_parent(self, tmp_path):
        import json

        from door.core.utils import write_json_atomic

        target = tmp_path / "a" / "b.json"
        write_json_atomic(target, {"name": "Søren"})
        assert json.loads(target.read_text(encoding="utf-8")) == {"name": "Søren"}
        assert "Søren" in target.read_text(encoding="utf-8")
        assert list(target.parent.iterdir()) == [target]

    def test_failed_write_leaves_target_and_no_tmp(self, tmp_path):
        from door.core.utils import write_json_atomic

        target = tmp_path / "b.json"
        target.write_text("{}", encoding="utf-8")
        with pytest.raises(TypeError):
            write_json_atomic(target, {"bad": object()}, default=None)
        assert target.read_text(encoding="utf-8") == "{}"
        assert list(tmp_path.iterdir()) == [target]


# --------------------------------------------------------------------------- #
# write_atomic
# --------------------------------------------------------------------------- #

class TestWriteAtomic:
    def test_text_and_bytes(self, tmp_path):
        from door.core.utils import write_atomic

        write_atomic(tmp_path / "a" / "t.txt", "Søren\n")
        write_atomic(tmp_path / "b.bin", b"\x00\x01")
        assert (tmp_path / "a" / "t.txt").read_bytes() == "Søren\n".encode()
        assert (tmp_path / "b.bin").read_bytes() == b"\x00\x01"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["a", "b.bin"]

    def test_writers_never_share_a_temp_name(self, tmp_path, monkeypatch):
        import os

        from door.core.utils import write_atomic

        sources = []
        real = os.replace
        monkeypatch.setattr(os, "replace", lambda s, d: (sources.append(str(s)), real(s, d))[1])
        write_atomic(tmp_path / "x.json", "1")
        write_atomic(tmp_path / "x.json", "2")
        assert len(set(sources)) == 2

    def test_mode_is_set_before_data_is_written(self, tmp_path, monkeypatch):
        import os
        import stat
        import sys

        from door.core.utils import write_atomic

        if sys.platform == "win32":
            pytest.skip("POSIX modes")
        seen = []
        real = open

        def spy(file, *a, **k):
            seen.append(stat.S_IMODE(os.stat(file).st_mode))
            return real(file, *a, **k)

        monkeypatch.setattr("door.core.utils.open", spy, raising=False)
        write_atomic(tmp_path / "s.json", "{}", mode=0o600)
        assert seen == [0o600]
        assert stat.S_IMODE((tmp_path / "s.json").stat().st_mode) == 0o600

    def test_failure_leaves_no_temp_file(self, tmp_path):
        from door.core.utils import write_atomic

        with pytest.raises(TypeError):
            write_atomic(tmp_path / "f.txt", 5)  # type: ignore[arg-type]
        assert list(tmp_path.iterdir()) == []

    def test_new_file_follows_the_umask(self, tmp_path, monkeypatch):
        import os
        import stat
        import sys

        from door.core.utils import write_atomic

        if sys.platform == "win32":
            pytest.skip("POSIX modes")
        from door.core import utils

        monkeypatch.setattr(utils, "_UMASK", 0o077)
        write_atomic(tmp_path / "n.json", "{}")
        assert stat.S_IMODE((tmp_path / "n.json").stat().st_mode) == 0o600

    def test_a_write_never_touches_the_process_umask(self, tmp_path, monkeypatch):
        import os

        from door.core import utils

        def no(*_a):
            raise AssertionError("os.umask called during a write")

        monkeypatch.setattr(os, "umask", no)
        utils.write_atomic(tmp_path / "new.txt", "x")

    def test_mode_over_an_existing_file_wins(self, tmp_path):
        import os
        import stat
        import sys

        from door.core.utils import write_atomic

        if sys.platform == "win32":
            pytest.skip("POSIX modes")
        f = tmp_path / "e.json"
        f.write_text("old")
        os.chmod(f, 0o644)
        write_atomic(f, "new", mode=0o600)
        assert stat.S_IMODE(f.stat().st_mode) == 0o600

    def test_no_mode_keeps_the_existing_mode(self, tmp_path):
        import os
        import stat
        import sys

        from door.core.utils import write_atomic

        if sys.platform == "win32":
            pytest.skip("POSIX modes")
        f = tmp_path / "k.json"
        f.write_text("old")
        os.chmod(f, 0o640)
        write_atomic(f, "new")
        assert stat.S_IMODE(f.stat().st_mode) == 0o640

    def test_chmod_failure_closes_the_fd_and_leaves_no_temp(self, tmp_path, monkeypatch):
        import os

        from door.core.utils import write_atomic

        def boom(*a, **k):
            raise PermissionError("no")

        monkeypatch.setattr(os, "chmod", boom)
        with pytest.raises(PermissionError):
            write_atomic(tmp_path / "c.txt", "x")
        assert list(tmp_path.iterdir()) == []


def test_atomic_target_failure_leaves_target_and_no_temp(tmp_path):
    from door.core.utils import atomic_target

    target = tmp_path / "sub" / "out.bin"
    target.parent.mkdir()
    target.write_bytes(b"old")
    with pytest.raises(RuntimeError):
        with atomic_target(target, mode=0o600) as tmp:
            tmp.write_bytes(b"new")
            raise RuntimeError("boom")
    assert target.read_bytes() == b"old"
    assert [p.name for p in target.parent.iterdir()] == ["out.bin"]


def test_fair_share_takes_each_group_in_turn_best_first():
    from door.core.utils import fair_share

    items = [("a", 3), ("a", 9), ("a", 5), ("b", 1), ("c", 2), ("c", 7)]
    chosen, rest = fair_share(items, 4, key=lambda i: i[0], rank=lambda i: -i[1])
    assert chosen == [("a", 9), ("c", 7), ("b", 1), ("a", 5)]
    assert sorted(rest) == [("a", 3), ("c", 2)]
    assert fair_share(items, 99, key=lambda i: i[0], rank=lambda i: -i[1])[1] == []


def test_folder_masker_replaces_the_longest_folder_first_in_every_spelling(tmp_path):
    from door.core import utils

    inner = tmp_path / "data"
    mask = utils.folder_masker({tmp_path: "~", inner: "<data folder>"})
    assert mask(f"{inner}/jobs and {tmp_path}/other and {inner.resolve()}/x") == "<data folder>/jobs and ~/other and <data folder>/x"
