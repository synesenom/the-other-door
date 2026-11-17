"""`style_extract.extract` as it was before the structure came from a model (#343): the name, headings, columns and the
LinkedIn and layout verdicts from the rules (`find_name`, `find_headings`, `column_bands`, `style_verdict`,
`layout_verdict`). Production no longer calls them; their unit tests do, through this, until #344 deletes both."""

from door.tailoring import style_extract as se


def rules_extract(path):
    pages = se.read_pages(path)
    verdict = se.style_verdict(pages)
    if not verdict["copyable"]:
        return {"version": se.VERSION, "verdict": verdict, "page_count": len(pages)}
    found = se.extract(path)
    runs = [r for p in pages for r in p["runs"]]
    shapes = [s for p in pages for s in p["shapes"]]
    columns = se.column_bands(pages, shapes)
    name = se.find_name(runs)
    headings = se.find_headings(runs, shapes, columns["bands"], name)
    return {**found, "verdict": se.layout_verdict(columns) or verdict, "name": name, "columns": columns,
            "headings": headings, "heading_style": se.heading_style(headings)}
