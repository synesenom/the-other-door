"""door.style.style_structure (#343): a CV's structure read by one model call, checked in code, cached by the file.
The call itself (`claude_cli.ask`) is faked here; no test reaches a model."""

import json
import os

import pytest

from pdf_utils import raw_pdf

from door.core import claude_cli, workspace
from door.style import style_extract, style_structure
from door.style.style_structure import StructureError


def put(font, size, x, y, s, color="0 0 0"):
    return f"BT /{font} {size} Tf {color} rg {x} {y} Td ({s}) Tj ET\n"


def filler(x, y, n=4, size=10):
    return "".join(put("F1", size, x, y - 13 * i, "Built and ran services for many people each day") for i in range(n))


def one_column(heads=("Experience", "Education", "Skills"), title_font="F2", dates="2019 - 2022"):
    out = put("F2", 20, 50, 800, "Max Mustermann") + put("F1", 10, 50, 782, "max@example.com +49 30 1234567")
    y = 740
    for h in heads:
        out += put("F2", 13, 50, y, h)
        out += put(title_font, 10, 50, y - 18, "Senior Developer, Firma AG") + put("F1", 10, 450, y - 18, dates)
        out += filler(60, y - 32, 3)
        y -= 110
    return out


def two_columns():
    out = put("F2", 20, 200, 800, "Max Mustermann")
    out += put("F2", 13, 200, 740, "Experience") + filler(200, 720, 6) + put("F2", 13, 200, 600, "Education") + filler(200, 580, 5)
    out += put("F2", 13, 40, 740, "Skills") + "".join(put("F1", 10, 40, 722 - 13 * i, f"Skill {i}") for i in range(6))
    out += put("F2", 13, 40, 600, "Languages") + "".join(put("F1", 10, 40, 582 - 13 * i, f"Language {i}") for i in range(4))
    return out


def pdf_of(tmp_path, content, name="cv.pdf", **kw):
    path = tmp_path / name
    path.write_bytes(raw_pdf(content, **kw))
    return path


def read(path):
    pages = style_extract.read_pages(path)
    return pages, *reversed(style_structure.rows(pages))


def ids_by_text(rows):
    return {r["text"]: r["id"] for r in rows}


def answer(rows, name="Max Mustermann", heads=("Experience", "Education", "Skills"), layout=None, **extra):
    ids = ids_by_text(rows)
    return {"linkedin_export": False, "layout": layout or {"columns": "one"}, "name": ids[name],
            "headings": [{"id": ids[h], "kind": "other"} for h in heads], "entry_titles": [], "contacts": [], "footers": [], **extra}


# ---------- the input ----------

def test_rows_are_numbered_from_one_in_reading_order_with_their_place_and_style(tmp_path):
    pages, rows, text = read(pdf_of(tmp_path, one_column()))
    assert [r["id"] for r in rows] == list(range(1, len(rows) + 1))
    assert rows[0]["text"] == "Max Mustermann" and rows[0]["page"] == 1 and abs(rows[0]["x0"] - 50) <= 2
    assert [r["text"] for r in rows[:3]] == ["Max Mustermann", "max@example.com +49 30 1234567", "Experience"]
    assert "styles (id family size weight italic colour chars):" in text and "1 1 " in text.replace("\n", "\n")
    assert f"{rows[0]['id']} 1 {rows[0]['y']} {rows[0]['x0']} {rows[0]['x1']} {rows[0]['style']} Max Mustermann" in text


def test_the_input_is_deterministic(tmp_path):
    path = pdf_of(tmp_path, one_column())
    assert read(path)[2] == read(path)[2]


def test_a_gap_wider_than_a_word_or_two_splits_a_line_into_rows(tmp_path):
    # a title and its date on one baseline are two rows: they are not one piece of text
    _, rows, _ = read(pdf_of(tmp_path, put("F2", 10, 50, 700, "Title") + put("F1", 10, 450, 700, "2019 - 2022") + filler(50, 680)))
    assert [r["text"] for r in rows][:2] == ["Title", "2019 - 2022"]


def test_a_font_change_together_with_a_new_baseline_splits_a_piece(tmp_path):
    content = put("F2", 14, 50, 700, "Big") + put("F1", 9, 75, 690, "small") + filler(50, 670)
    _, rows, _ = read(pdf_of(tmp_path, content))
    assert [r["text"] for r in rows][:2] == ["Big", "small"]


def test_a_row_that_mixes_styles_says_so(tmp_path):
    content = put("F2", 14, 50, 700, "A") + put("F2", 9, 60, 700, "SMALLER CAPS") + filler(50, 680)
    _, rows, _ = read(pdf_of(tmp_path, content))
    assert rows[0]["style"].endswith("*")


# ---------- the checks ----------

@pytest.fixture
def cv(tmp_path):
    pages, rows, _ = read(pdf_of(tmp_path, one_column()))
    return pages, rows


def test_a_good_answer_gives_the_name_headings_and_one_column(cv):
    pages, rows = cv
    s = style_structure.check(answer(rows), rows, pages)
    assert s["columns"] == "one" and s["name"]["text"] == "Max Mustermann" and s["linkedin"] is False
    assert [(h["text"], h["column"]) for h in s["headings"]] == [("Experience", "main"), ("Education", "main"), ("Skills", "main")]


@pytest.mark.parametrize("break_it,why", [
    (lambda a, ids: a["headings"].append({"id": 999, "kind": "other"}), "does not exist"),
    (lambda a, ids: a.update(name=999), "name"),
    (lambda a, ids: a["headings"].append(dict(a["headings"][0])), "twice"),
    (lambda a, ids: a["headings"].append({"id": a["name"], "kind": "other"}), "name"),
    (lambda a, ids: a.update(headings=a["headings"][:1]), "fewer than two"),
    (lambda a, ids: a["headings"].extend({"id": ids[t], "kind": "other"}
                                         for t in ("Senior Developer, Firma AG", "max@example.com +49 30 1234567")), "2 styles"),
    (lambda a, ids: a["entry_titles"].append(999), "does not exist"),
    (lambda a, ids: a.update(layout={"columns": "four"}), "layout"),
    (lambda a, ids: a.update(headings="x"), "headings"),
])
def test_an_answer_that_does_not_hold_is_refused_in_words(cv, break_it, why):
    pages, rows = cv
    a = answer(rows)
    break_it(a, ids_by_text(rows))
    with pytest.raises(StructureError) as refused:
        style_structure.check(a, rows, pages)
    assert why in refused.value.detail and "look of this CV could not be read" in str(refused.value)


def test_a_heading_of_more_than_six_words_is_refused(tmp_path):
    long = "Professional experience and positions held over many years"
    pages, rows, _ = read(pdf_of(tmp_path, one_column(heads=(long, "Education", "Skills"))))
    with pytest.raises(StructureError, match="look of this CV"):
        style_structure.check(answer(rows, heads=(long, "Education", "Skills")), rows, pages)


def test_headings_in_more_than_two_styles_are_refused(tmp_path):
    content = one_column() + put("F5", 15, 50, 300, "Projects") + put("F3", 11, 50, 250, "Awards")
    pages, rows, _ = read(pdf_of(tmp_path, content))
    with pytest.raises(StructureError, match="look of this CV"):
        style_structure.check(answer(rows, heads=("Experience", "Projects", "Awards")), rows, pages)


def test_the_model_s_column_for_a_heading_is_ignored_and_worked_out_from_its_x(tmp_path):
    pages, rows, _ = read(pdf_of(tmp_path, two_columns()))
    ids = ids_by_text(rows)
    a = {"linkedin_export": False, "layout": {"columns": "two", "side_x0": 38, "side_x1": 120},
         "name": ids["Max Mustermann"], "entry_titles": [], "contacts": [], "footers": [],
         "headings": [{"id": ids[h], "kind": "other"} for h in ("Experience", "Education", "Skills", "Languages")]}
    s = style_structure.check(a, rows, pages)
    assert {h["text"]: h["column"] for h in s["headings"]} == {"Experience": "main", "Education": "main", "Skills": "side", "Languages": "side"}
    assert 38 <= s["side_range"][0] <= 40 and s["side_range"][1] <= 140


@pytest.mark.parametrize("layout,why", [
    ({"columns": "two"}, "side column"),
    ({"columns": "two", "side_x0": 38, "side_x1": 900}, "inside the page"),
    ({"columns": "two", "side_x0": 38, "side_x1": 480}, "narrower"),
    ({"columns": "two", "side_x0": 100, "side_x1": 120}, "no text"),
])
def test_two_columns_need_a_side_range_that_fits_the_page_and_the_text(tmp_path, layout, why):
    pages, rows, _ = read(pdf_of(tmp_path, two_columns()))
    ids = ids_by_text(rows)
    a = {"linkedin_export": False, "layout": layout, "name": ids["Max Mustermann"], "entry_titles": [], "contacts": [], "footers": [],
         "headings": [{"id": ids[h], "kind": "other"} for h in ("Experience", "Skills")]}
    with pytest.raises(StructureError) as refused:
        style_structure.check(a, rows, pages)
    assert why in refused.value.detail and "look of this CV could not be read" in str(refused.value)


def test_three_columns_are_a_layout_verdict(tmp_path):
    pages, rows, _ = read(pdf_of(tmp_path, one_column()))
    s = style_structure.check(answer(rows, layout={"columns": "three_or_more"}), rows, pages)
    assert s["columns"] == "three"
    assert style_extract.structure_verdict(s)["reason"] == "layout"


def test_linkedin_is_believed_only_with_a_page_footer_on_every_page(tmp_path):
    pages, rows, _ = read(pdf_of(tmp_path, one_column()))
    assert style_structure.check(answer(rows, linkedin_export=True), rows, pages)["linkedin"] is False
    footed = one_column() + put("F1", 8, 270, 30, "Page 1 of 1")
    pages, rows, _ = read(pdf_of(tmp_path, footed, "footed.pdf"))
    s = style_structure.check(answer(rows, linkedin_export=True, footers=[ids_by_text(rows)["Page 1 of 1"]]), rows, pages)
    assert s["linkedin"] is True and style_extract.structure_verdict(s)["reason"] == "linkedin"


def test_a_footer_on_one_page_of_two_is_no_linkedin_export(tmp_path):
    pages = [one_column() + put("F1", 8, 270, 30, "Page 1 of 2"), filler(50, 700)]
    pages_, rows, _ = read(pdf_of(tmp_path, pages))
    a = answer(rows, linkedin_export=True, footers=[ids_by_text(rows)["Page 1 of 2"]])
    assert style_structure.check(a, rows, pages_)["linkedin"] is False


def test_the_models_kind_for_a_heading_is_kept_whatever_the_words(cv):
    pages, rows = cv
    a = answer(rows)
    a["headings"][0]["kind"] = "skills"
    a["headings"][2]["kind"] = "languages"
    assert [h["kind"] for h in style_structure.check(a, rows, pages)["headings"]] == ["skills", "other", "languages"]


def test_the_contact_lines_and_footers_are_carried_in_the_structure(tmp_path):
    pages, rows, _ = read(pdf_of(tmp_path, one_column() + put("F1", 8, 270, 30, "Page 1 of 1")))
    ids = ids_by_text(rows)
    a = answer(rows, contacts=[{"id": ids["max@example.com +49 30 1234567"], "kind": "email", "label": "E-mail:"}],
               footers=[ids["Page 1 of 1"]])
    s = style_structure.check(a, rows, pages)
    assert [(c["row"]["id"], c["kind"]) for c in s["contacts"]] == [(ids["max@example.com +49 30 1234567"], "email")]
    assert [r["id"] for r in s["footers"]] == [ids["Page 1 of 1"]]


@pytest.mark.parametrize("break_it", [
    lambda a, ids: a["contacts"].append({"id": 999, "kind": "phone"}),
    lambda a, ids: a["contacts"].append({"id": ids["Experience"], "kind": "fax"}),
    lambda a, ids: a.update(contacts=[{"id": ids["Experience"], "kind": "phone"}] * 2),
    lambda a, ids: a.update(contacts="x"),
    lambda a, ids: a.update(footers=[999]),
    lambda a, ids: a.pop("footers"),
    lambda a, ids: a.pop("contacts"),
])
def test_contacts_and_footers_that_do_not_hold_are_refused(cv, break_it):
    pages, rows = cv
    a = answer(rows)
    break_it(a, ids_by_text(rows))
    with pytest.raises(StructureError):
        style_structure.check(a, rows, pages)


def test_a_heading_that_wraps_takes_its_second_line_in(tmp_path):
    content = (put("F2", 20, 50, 800, "Max Mustermann") + put("F2", 12, 50, 740, "Professional")
               + put("F2", 12, 50, 726, "Experience") + filler(50, 700) + put("F2", 12, 50, 600, "Education") + filler(50, 580))
    pages, rows, _ = read(pdf_of(tmp_path, content))
    s = style_structure.check(answer(rows, heads=("Professional", "Education")), rows, pages)
    assert [h["text"] for h in s["headings"]] == ["Professional Experience", "Education"]
    assert s["headings"][0]["bbox"][3] > s["headings"][0]["row"]["bbox"][3]


def test_a_heading_set_like_the_body_does_not_take_the_next_body_line(tmp_path):
    content = (put("F2", 20, 50, 800, "Max Mustermann") + put("F1", 10, 50, 740, "EXPERIENCE") + filler(50, 727)
               + put("F1", 10, 50, 650, "EDUCATION") + filler(50, 637))
    pages, rows, _ = read(pdf_of(tmp_path, content))
    s = style_structure.check(answer(rows, heads=("EXPERIENCE", "EDUCATION")), rows, pages)
    assert [h["text"] for h in s["headings"]] == ["EXPERIENCE", "EDUCATION"]


# ---------- the call and its cache ----------

class Asks:
    """`claude_cli.ask`'s stand-in: answers by the rows it is given, counts its calls."""

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, system, text, **kwargs):
        self.calls.append({"system": system, "text": text, **kwargs})
        reply = self.reply(text) if callable(self.reply) else self.reply
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def ask(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace, "HOME", tmp_path / "home")

    def install(reply):
        asks = Asks(reply)
        monkeypatch.setattr(claude_cli, "ask", asks)
        return asks

    return install


def good(text):
    by_text = {" ".join(row.split(" ")[6:]): int(row.split(" ")[0])
               for row in text.split("lines (", 1)[1].splitlines()[1:]}
    return {"linkedin_export": False, "layout": {"columns": "one"}, "name": by_text["Max Mustermann"],
            "headings": [{"id": by_text[h], "kind": "other"} for h in ("Experience", "Education", "Skills")],
            "entry_titles": [], "contacts": [], "footers": []}


def test_a_scan_is_not_asked_about(tmp_path, ask):
    asks = ask(good)
    assert style_structure.structure_for(pdf_of(tmp_path, put("F1", 10, 50, 700, "x"), "scan.pdf")) is None
    assert asks.calls == []


def test_the_call_is_haiku_at_low_effort_with_no_mcp_servers_and_the_style_feature(tmp_path, ask):
    asks = ask(good)
    style_structure.structure_for(pdf_of(tmp_path, one_column()))
    call = asks.calls[0]
    assert call["system"] == "cv-structure" and "Max Mustermann" in call["text"]
    assert claude_cli.model_of("cv-structure") == "haiku" and call["feature"] == "style" and call["schema"] == style_structure.SCHEMA
    assert call["effort"] == "low" and call["timeout_s"] == 60


def test_the_answer_is_cached_by_the_files_sha256_and_a_second_read_makes_no_call(tmp_path, ask):
    asks = ask(good)
    path = pdf_of(tmp_path, one_column())
    first = style_structure.structure_for(path)
    assert len(list((workspace.HOME / ".style" / "structure").glob("*.json"))) == 1
    copy = tmp_path / "elsewhere.pdf"
    copy.write_bytes(path.read_bytes())  # the same file under another name: the same key
    second = style_structure.structure_for(copy)
    assert len(asks.calls) == 1 and [h["text"] for h in second["headings"]] == [h["text"] for h in first["headings"]]
    cached = json.loads(next((workspace.HOME / ".style" / "structure").glob("*.json")).read_text())
    assert cached["version"] == style_structure.PROMPT_VERSION and cached["answer"]["name"]
    assert not list((workspace.HOME / ".style" / "structure").glob("*.tmp"))


def test_another_prompt_version_asks_again(tmp_path, ask, monkeypatch):
    asks = ask(good)
    path = pdf_of(tmp_path, one_column())
    style_structure.structure_for(path)
    monkeypatch.setattr(style_structure, "PROMPT_VERSION", style_structure.PROMPT_VERSION + 1)
    style_structure.structure_for(path)
    assert len(asks.calls) == 2


def test_a_broken_answer_is_an_error_in_words_and_is_never_cached(tmp_path, ask):
    ask(lambda text: {**good(text), "name": 9999})
    with pytest.raises(StructureError, match="The look of this CV could not be read") as refused:
        style_structure.structure_for(pdf_of(tmp_path, one_column()))
    assert "name" in refused.value.detail
    assert not (workspace.HOME / ".style" / "structure").exists() or not list((workspace.HOME / ".style" / "structure").iterdir())


def test_an_answer_that_does_not_hold_is_asked_once_more_and_the_second_kept(tmp_path, ask):
    answers = iter([lambda text: {**good(text), "name": 9999}, good])  # the model's answers vary run to run
    asks = ask(lambda text: next(answers)(text))
    assert style_structure.structure_for(pdf_of(tmp_path, one_column()))["name"]["text"] == "Max Mustermann"
    assert len(asks.calls) == 2


def test_two_answers_that_do_not_hold_are_refused_after_the_second(tmp_path, ask):
    asks = ask(lambda text: {**good(text), "name": 9999})
    with pytest.raises(StructureError):
        style_structure.structure_for(pdf_of(tmp_path, one_column()))
    assert len(asks.calls) == 2


def test_a_failed_call_is_an_error_in_plain_words_with_no_fallback_and_no_internal_text(tmp_path, ask):
    ask(claude_cli.ClaudeError("claude -p timed out after 60s"))
    with pytest.raises(StructureError) as failed:
        style_structure.structure_for(pdf_of(tmp_path, one_column()))
    assert str(failed.value) == "Claude could not be reached, or Claude's usage limit is reached. Try again later."
    assert "timed out" in failed.value.detail and "timed out" not in str(failed.value)


def test_a_cached_answer_that_no_longer_holds_is_dropped_and_asked_once_again(tmp_path, ask):
    asks = ask(good)
    path = pdf_of(tmp_path, one_column())
    style_structure.structure_for(path)
    cache = next((workspace.HOME / ".style" / "structure").glob("*.json"))
    data = json.loads(cache.read_text())
    data["answer"]["name"] = 9999
    cache.write_text(json.dumps(data))
    assert style_structure.structure_for(path)["name"]["text"] == "Max Mustermann"
    assert len(asks.calls) == 2
    assert json.loads(cache.read_text())["answer"]["name"] != 9999


def test_an_answer_cached_for_other_rows_is_a_miss(tmp_path, ask):
    asks = ask(good)
    path = pdf_of(tmp_path, one_column())
    style_structure.structure_for(path)
    cache = next((workspace.HOME / ".style" / "structure").glob("*.json"))
    data = json.loads(cache.read_text())
    assert len(data["rows"]) == 64
    data["rows"] = "0" * 64
    cache.write_text(json.dumps(data))
    style_structure.structure_for(path)
    assert len(asks.calls) == 2


def test_the_cache_keeps_the_twenty_most_recent_answers(tmp_path, ask):
    ask(good)
    folder = workspace.HOME / ".style" / "structure"
    folder.mkdir(parents=True)
    for n in range(25):
        old = folder / f"{n:064d}.json"
        old.write_text("{}")
        os.utime(old, (1000 + n, 1000 + n))
    style_structure.structure_for(pdf_of(tmp_path, one_column()))
    kept = {f.name for f in folder.glob("*.json")}
    assert len(kept) == 20 and f"{0:064d}.json" not in kept and f"{24:064d}.json" in kept
    assert any(not name.startswith("0000") for name in kept)  # the new one


def test_a_heading_with_no_known_kind_is_refused_not_a_key_error(cv):
    pages, rows = cv
    a = answer(rows)
    del a["headings"][0]["kind"]
    with pytest.raises(StructureError) as refused:
        style_structure.check(a, rows, pages)
    assert "kind" in refused.value.detail
    a["headings"][0]["kind"] = "hobbies"
    with pytest.raises(StructureError):
        style_structure.check(a, rows, pages)


def test_the_structure_call_is_billed_under_the_feature_it_is_given(tmp_path, ask):
    asks = ask(good)
    style_structure.structure_for(pdf_of(tmp_path, one_column()), feature="draft_cv")
    assert asks.calls[0]["feature"] == "draft_cv"


def test_the_schema_asks_for_no_column_and_no_side_of_the_model():
    heading = style_structure.SCHEMA["properties"]["headings"]["items"]["properties"]
    layout = style_structure.SCHEMA["properties"]["layout"]["properties"]
    assert set(heading) == {"id", "kind"} and set(layout) == {"columns", "side_x0", "side_x1"}


def test_a_cache_file_that_is_not_json_is_asked_again(tmp_path, ask):
    asks = ask(good)
    path = pdf_of(tmp_path, one_column())
    style_structure.structure_for(path)
    next((workspace.HOME / ".style" / "structure").glob("*.json")).write_text("{")
    style_structure.structure_for(path)
    assert len(asks.calls) == 2


def test_extract_reads_the_structure_into_the_style(tmp_path, ask):
    ask(good)
    style = style_structure.extract(pdf_of(tmp_path, one_column()))
    assert style["name"]["text"] == "Max Mustermann" and [h["text"] for h in style["headings"]] == ["Experience", "Education", "Skills"]
    assert style["columns"]["bands"][0]["kind"] == "only"


# ---------- extract given a structure ----------

def structured(tmp_path, content, **kw):
    path = pdf_of(tmp_path, content, **kw)
    pages, rows, _ = read(path)
    return path, pages, rows


def test_extract_without_a_structure_reads_no_name_headings_or_columns(tmp_path):
    style = style_extract.extract(pdf_of(tmp_path, one_column()))
    assert style["name"] is None and style["headings"] == [] and style["heading_style"] is None
    assert style["columns"] == {"count": 0, "bands": []} and style["verdict"]["copyable"] and style["runs"]


def test_a_scan_has_the_scan_verdict_with_or_without_a_structure(tmp_path):
    path = pdf_of(tmp_path, put("F1", 10, 50, 700, "x"), "scan.pdf")
    assert style_extract.extract(path)["verdict"]["reason"] == "scan"


def test_entry_titles_in_the_headings_style_give_only_the_headings(tmp_path):
    path, pages, rows = structured(tmp_path, one_column(title_font="F2"))
    s = style_structure.check(answer(rows), rows, pages)
    style = style_extract.extract(path, structure=s)
    assert [h["text"] for h in style["headings"]] == ["Experience", "Education", "Skills"]
    assert style["heading_style"]["size"] == 13.0


def test_a_one_column_cv_has_one_only_band_over_its_text(tmp_path):
    path, pages, rows = structured(tmp_path, one_column())
    band = style_extract.extract(path, structure=style_structure.check(answer(rows), rows, pages))["columns"]["bands"]
    assert [b["kind"] for b in band] == ["only"] and abs(band[0]["x0"] - 50) <= 2 and band[0]["x1"] > 450


def test_two_columns_are_a_side_band_and_a_main_band_left_to_right_with_the_headings_in_their_bands(tmp_path):
    path, pages, rows = structured(tmp_path, two_columns())
    ids = ids_by_text(rows)
    a = {"linkedin_export": False, "layout": {"columns": "two", "side_x0": 38, "side_x1": 120},
         "name": ids["Max Mustermann"], "entry_titles": [], "contacts": [], "footers": [],
         "headings": [{"id": ids[h], "kind": "other"} for h in ("Experience", "Education", "Skills", "Languages")]}
    style = style_extract.extract(path, structure=style_structure.check(a, rows, pages))
    assert [b["kind"] for b in style["columns"]["bands"]] == ["side", "main"] and style["columns"]["count"] == 2
    assert {h["text"]: h["band"] for h in style["headings"]} == {"Experience": "main", "Education": "main", "Skills": "side", "Languages": "side"}


def test_a_side_band_on_a_box_has_its_background(tmp_path):
    box = "0.9 0.9 0.8 rg 0 0 160 842 re f\n"
    path, pages, rows = structured(tmp_path, box + two_columns())
    ids = ids_by_text(rows)
    a = {"linkedin_export": False, "layout": {"columns": "two", "side_x0": 38, "side_x1": 120},
         "name": ids["Max Mustermann"], "entry_titles": [], "contacts": [], "footers": [],
         "headings": [{"id": ids[h], "kind": "other"} for h in ("Experience", "Skills")]}
    bands = style_extract.extract(path, structure=style_structure.check(a, rows, pages))["columns"]["bands"]
    assert bands[0]["background"] == "#e6e6cc" and bands[1]["background"] is None


def test_three_columns_refuse_with_the_layout_verdict_and_keep_the_rest(tmp_path):
    path, pages, rows = structured(tmp_path, one_column())
    s = style_structure.check(answer(rows, layout={"columns": "three_or_more"}), rows, pages)
    style = style_extract.extract(path, structure=s)
    assert style["verdict"]["reason"] == "layout" and style["runs"] and style["colors"]


def test_a_linkedin_export_has_only_the_verdict(tmp_path):
    path, pages, rows = structured(tmp_path, one_column() + put("F1", 8, 270, 30, "Page 1 of 1"))
    a = answer(rows, linkedin_export=True, footers=[ids_by_text(rows)["Page 1 of 1"]])
    style = style_extract.extract(path, structure=style_structure.check(a, rows, pages))
    assert style["verdict"]["reason"] == "linkedin" and "runs" not in style


def lines(x, y, n, label):
    return "".join(put("F1", 10, x, y - 13 * i, f"{label} {i}") for i in range(n))


def three_strips(right_rows):
    out = put("F2", 20, 40, 800, "Max Mustermann")
    out += put("F2", 13, 40, 740, "Experience") + lines(40, 722, 6, "Main line")
    out += put("F2", 13, 250, 740, "Skills") + lines(250, 722, 6, "Side line")
    return out + lines(420, 722, right_rows, "Note")


def test_text_wholly_on_both_sides_of_the_side_range_is_a_third_column(tmp_path):
    pages, rows, _ = read(pdf_of(tmp_path, three_strips(4)))
    a = answer(rows, heads=("Experience", "Skills"), layout={"columns": "two", "side_x0": 248, "side_x1": 300})
    s = style_structure.check(a, rows, pages)
    assert s["columns"] == "three" and s["side_range"] is None
    assert style_extract.structure_verdict(s)["reason"] == "layout"


def test_a_sidebar_with_one_stray_row_beyond_it_stays_two_columns(tmp_path):
    out = put("F2", 20, 40, 800, "Max Mustermann")
    out += put("F2", 13, 40, 740, "Experience") + lines(40, 722, 6, "Main line")
    out += put("F2", 13, 400, 740, "Skills") + lines(400, 722, 6, "Side line") + put("F1", 8, 560, 30, "2")
    pages, rows, _ = read(pdf_of(tmp_path, out))
    a = answer(rows, heads=("Experience", "Skills"), layout={"columns": "two", "side_x0": 398, "side_x1": 460})
    s = style_structure.check(a, rows, pages)
    assert s["columns"] == "two"


# ---------- icons, kinds and footers from the structure ----------

def _icon_cv(lines):
    """A one-column CV with a small star drawn before each of `lines`, (text, y) in the header."""
    import math

    def star(cx, cy, r):
        pts = [(cx + (r if i % 2 == 0 else r * 0.4) * math.sin(i * math.pi / 5),
                cy + (r if i % 2 == 0 else r * 0.4) * math.cos(i * math.pi / 5)) for i in range(10)]
        return "1 0 0 rg " + f"{pts[0][0]:.2f} {pts[0][1]:.2f} m " + " ".join(f"{x:.2f} {y:.2f} l" for x, y in pts[1:]) + " f\n"

    out = put("F2", 20, 50, 800, "Max Mustermann")
    for label, y in lines:
        out += star(55, y + 3, 5) + put("F1", 10, 70, y, label)
    header = put("F2", 20, 50, 800, "Max Mustermann") + put("F1", 10, 50, 782, "max@example.com +49 30 1234567")
    return out + one_column()[len(header):]


def test_an_icon_gets_its_kind_from_the_model_s_contact_line_in_a_language_no_table_knows(tmp_path):
    path = pdf_of(tmp_path, _icon_cv([("Puhelin 040 1234567", 782), ("Helsinki", 765), ("1999 - 2003", 748), ("Reading", 731)]))
    pages, rows, _ = read(path)
    ids = ids_by_text(rows)
    contacts = [{"id": ids["Puhelin 040 1234567"], "kind": "phone", "label": "Puhelin"},
                {"id": ids["Helsinki"], "kind": "location"},
                {"id": ids["1999 - 2003"], "kind": "date"}]
    style = style_extract.extract(path, structure=style_structure.check(answer(rows, contacts=contacts), rows, pages))
    assert [(i["near"]["text"], i["kind"]) for i in style["icons"]] == [
        ("Puhelin 040 1234567", "phone"), ("Helsinki", "location"), ("1999 - 2003", "date"), ("Reading", None)]


def test_an_icon_with_no_structure_has_no_kind(tmp_path):
    style = style_extract.extract(pdf_of(tmp_path, _icon_cv([("a@example.com", 782)])))
    assert [i["kind"] for i in style["icons"]] == [None]


def test_the_footers_the_model_names_are_left_out_of_the_margins(tmp_path):
    pages, rows, _ = read(pdf_of(tmp_path, [one_column() + put("F1", 8, 290, 30, "Page 1 of 2"), one_column()]))
    footer = next(r["id"] for r in rows if r["text"] == "Page 1 of 2")
    body_bottom = max(r["bbox"][3] for r in pages[0]["runs"] if "Page" not in r["text"])
    expected = round((pages[0]["size"][1] - body_bottom) * 2) / 2
    s = style_structure.check(answer(rows, footers=[footer]), rows, pages)
    assert style_extract.margins(pages, s)["bottom"] == expected
    assert style_extract.margins(pages)["bottom"] < 40 < expected  # no structure, no footers: the foot line counts


def test_a_footer_the_model_names_in_the_middle_of_a_page_is_dropped(tmp_path):
    pages, rows, _ = read(pdf_of(tmp_path, one_column() + put("F1", 8, 270, 30, "Page 1 of 1")))
    ids = ids_by_text(rows)
    a = answer(rows, linkedin_export=True, footers=[ids["Page 1 of 1"], ids["Education"]])
    s = style_structure.check(a, rows, pages)
    assert [r["text"] for r in s["footers"]] == ["Page 1 of 1"]
    a = answer(rows, linkedin_export=True, footers=[ids["Education"]])
    s = style_structure.check(a, rows, pages)
    assert s["footers"] == [] and s["linkedin"] is False


def test_with_no_structure_there_are_no_footers(tmp_path):
    pages = style_extract.read_pages(pdf_of(tmp_path, [one_column() + put("F1", 8, 290, 30, str(i)) for i in (1, 2)]))
    assert style_extract.footer_runs(pages, None) == []


def test_an_icon_whose_label_and_value_are_rows_of_their_own_gets_the_value_s_kind(tmp_path):
    import math

    star = "1 0 0 rg " + " ".join(
        f"{55 + (5 if i % 2 == 0 else 2) * math.sin(i * math.pi / 5):.2f} {785 + (5 if i % 2 == 0 else 2) * math.cos(i * math.pi / 5):.2f} {'m' if i == 0 else 'l'}"
        for i in range(10)) + " f\n"
    header = put("F2", 20, 50, 800, "Max Mustermann")
    content = header + star + put("F1", 10, 70, 782, "Telefon") + put("F1", 10, 200, 782, "+45 12 34 56 78") + one_column()[len(
        header + put("F1", 10, 50, 782, "max@example.com +49 30 1234567")):]
    path = pdf_of(tmp_path, content)
    pages, rows, _ = read(path)
    ids = ids_by_text(rows)
    contacts = [{"id": ids["+45 12 34 56 78"], "kind": "phone", "label": "Telefon"}]
    style = style_extract.extract(path, structure=style_structure.check(answer(rows, contacts=contacts), rows, pages))
    assert [i["kind"] for i in style["icons"]] == ["phone"]
