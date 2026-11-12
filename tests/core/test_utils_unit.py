"""Unit tests for utils.py helpers: _escape_latex, _normalize_text_for_ats, and _validate_job_id."""

import pytest

from door.core.utils import _escape_latex, _normalize_text_for_ats, _validate_job_id


# --------------------------------------------------------------------------- #
# _escape_latex
# --------------------------------------------------------------------------- #

class TestEscapeLatex:
    def test_clean_string_unchanged(self):
        assert _escape_latex("Hello World") == "Hello World"

    def test_backslash_not_double_escaped(self):
        # If backslash is replaced first, subsequent substitutions for other
        # chars should not re-escape the newly introduced backslashes.
        assert _escape_latex("\\&") == r"\textbackslash{}\&"

    def test_all_special_chars(self):
        result = _escape_latex(r"& % $ # _ { } ~ ^ \ ")
        assert result == r"\& \% \$ \# \_ \{ \} \~{} \^{} \textbackslash{} "


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
