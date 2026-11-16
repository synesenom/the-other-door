"""Eight made-up CVs for the style prototype (#154): one structured record each, drawn in a different design.

Everything here is invented (fake names, example.com); no real person's data. A record is
``{name, title, contact{phone,email,web,location}, summary, experience[{role,company,dates,bullets}],
education[{degree,school,dates}], skills[], languages[], extra_sections[{heading,items[]}]}``.
"""

from __future__ import annotations

import html
from pathlib import Path

from door.core import utils

REPO = Path(__file__).resolve().parents[2]

_PEOPLE = [
    ("Mira Valdis", "Data Engineer", "Copenhagen"), ("Jonas Brekke", "Product Designer", "Aarhus"),
    ("Lena Ortiz", "Backend Developer", "Odense"), ("Tomas Reyes", "Project Manager", "Malmo"),
    ("Nadia Holm", "Research Scientist", "Lund"), ("Pavel Dorn", "DevOps Engineer", "Gothenburg"),
    ("Ines Falk", "Marketing Analyst", "Aalborg"), ("Oskar Lind", "Frontend Developer", "Stockholm"),
]
_COMPANIES = ["Northwind Labs", "Bluebird Systems", "Kestrel Analytics", "Fjord Software", "Linden Works",
              "Harbor Digital", "Quill & Co", "Maple Robotics", "Tidewater Data", "Ember Studio"]
_BULLETS = [
    "Built and maintained services used by about 40 000 people a month.",
    "Cut the nightly pipeline from 3 hours to 25 minutes by rewriting its slowest stage.",
    "Led a team of 4 through a migration with no downtime.",
    "Wrote the onboarding guide that new colleagues still start from.",
    "Introduced code review and automated checks across 6 repositories.",
    "Presented results to management every quarter and agreed the next priorities.",
]
_SKILLS = ["Python", "SQL", "Docker", "Git", "Project planning", "Data analysis", "Figma", "TypeScript",
           "Communication", "Statistics"]


def record(n: int) -> dict:
    """The made-up CV number *n* (1-8)."""
    name, title, city = _PEOPLE[(n - 1) % len(_PEOPLE)]
    slug = name.lower().replace(" ", ".")
    jobs = [
        {"role": f"{title}", "company": _COMPANIES[(n + i) % len(_COMPANIES)],
         "dates": f"{2023 - 3 * i} - {'present' if i == 0 else 2023 - 3 * i + 3}",
         "bullets": [_BULLETS[(n + i + j) % len(_BULLETS)] for j in range(3)]}
        for i in range(3)
    ]
    return {
        "name": name, "title": title,
        "contact": {"phone": f"+45 20 30 40 {n}0", "email": f"{slug}@example.com",
                    "web": f"example.com/{slug}", "location": city},
        "summary": f"{title} with eight years of experience, who likes clear plans and small, steady steps.",
        "experience": jobs,
        "education": [{"degree": "MSc in Computer Science", "school": "Example University", "dates": "2013 - 2015"},
                      {"degree": "BSc in Mathematics", "school": "Example University", "dates": "2010 - 2013"}],
        "skills": [_SKILLS[(n + i) % len(_SKILLS)] for i in range(7)],
        "languages": ["English (fluent)", "Danish (native)", "French (basic)"],
        "extra_sections": [],
    }


def e(text: str) -> str:
    return html.escape(str(text), quote=False)


tex = utils._escape_latex  # *text* with LaTeX's special characters escaped


def _sections(r: dict) -> list[tuple[str, list[str]]]:
    return [(x["heading"], x["items"]) for x in r["extra_sections"]]


# ---------- default look: the shipped template's macros, the same text ----------

def to_default_tex(r: dict) -> str:
    template = (REPO / "profile.example" / "cv.template.tex").read_text(encoding="utf-8")
    template = template.replace("<<fonts>>", str(REPO / "profile.example" / "fonts"))
    c = r["contact"]
    body = [f"\\cvheader{{{tex(r['name'])}}}{{{tex(c['phone'])}}}{{{tex(c['email'])}}}{{{tex(c['web'])}}}"
            f"{{{tex(c['location'])}}}", "\\section{Profile}", tex(r["summary"]), "\\section{Work experience}"]
    for job in r["experience"]:
        items = "".join(f"\\item {tex(b)}\n" for b in job["bullets"])
        body.append(f"\\workexperience{{{tex(job['role'])} | {tex(job['company'])} --- {tex(job['dates'])}}}"
                    f"{{\\begin{{simplelist}}\n{items}\\end{{simplelist}}}}")
    body.append("\\section{Education}")
    body += [f"\\textbf{{{tex(x['degree'])}}}, {tex(x['school'])} ({tex(x['dates'])})\\par" for x in r["education"]]
    body += ["\\section{Skills}", tex(", ".join(r["skills"])) + "\\par", "\\section{Languages}",
             tex(", ".join(r["languages"])) + "\\par"]
    for heading, items in _sections(r):
        body += [f"\\section{{{tex(heading)}}}", tex("; ".join(items)) + "\\par"]
    head, _, _ = template.rpartition("\\end{document}")  # the last one: a comment names it too
    return head + "\n".join(body) + "\n\\end{document}\n"


# ---------- LaTeX designs ----------

def _latex(preamble: str, body: str) -> str:
    return ("\\documentclass[10pt,a4paper]{article}\n\\usepackage[utf8]{inputenc}\n\\usepackage[T1]{fontenc}\n"
            "\\usepackage{xcolor}\n\\usepackage{enumitem}\n\\usepackage{hyperref}\n"
            + preamble + "\n\\pagestyle{empty}\\setlength{\\parindent}{0pt}\n\\begin{document}\n" + body
            + "\n\\end{document}\n")


def _jobs_tex(r, head, bullet="\\textbullet"):
    out = []
    for j in r["experience"]:
        items = "".join(f"\\item {tex(b)}\n" for b in j["bullets"])
        out.append(head(j) + f"\n\\begin{{itemize}}[leftmargin=1.2em,noitemsep,topsep=2pt,label={bullet}]\n"
                   f"{items}\\end{{itemize}}")
    return "\n".join(out)


def latex_altacv(r: dict) -> str:
    c = r["contact"]
    pre = ("\\usepackage[margin=1.6cm]{geometry}\\usepackage{tgheros}\\renewcommand\\familydefault{\\sfdefault}\n"
           "\\definecolor{accent}{HTML}{0B7285}\\definecolor{muted}{HTML}{5C6770}\n"
           "\\newcommand{\\cvsec}[1]{\\par\\vspace{8pt}{\\color{accent}\\large\\bfseries\\MakeUppercase{#1}}\\\\[-3pt]"
           "{\\color{accent}\\rule{\\linewidth}{1pt}}\\vspace{3pt}\\par}")
    left = ("\\cvsec{Experience}\n" + _jobs_tex(r, lambda j: f"\\textbf{{{tex(j['role'])}}}\\hfill{{\\color{{muted}}"
            f"{tex(j['dates'])}}}\\\\{{\\color{{accent}}{tex(j['company'])}}}") + "\n\\cvsec{Education}\n"
            + "\n".join(f"\\textbf{{{tex(x['degree'])}}}\\\\{tex(x['school'])}, {tex(x['dates'])}\\\\[3pt]" for x in r["education"]))
    right = ("\\cvsec{Contact}\n" + "\\\\\n".join(tex(v) for v in c.values()) + "\n\\cvsec{Skills}\n"
             + "\\\\\n".join(tex(s) for s in r["skills"]) + "\n\\cvsec{Languages}\n" + "\\\\\n".join(tex(s) for s in r["languages"]))
    for h, items in _sections(r):
        left += f"\n\\cvsec{{{tex(h)}}}\n" + tex("; ".join(items))
    body = (f"{{\\color{{accent}}\\Huge\\bfseries {tex(r['name'])}}}\\\\[2pt]{{\\large\\color{{muted}}{tex(r['title'])}}}\\par\n"
            f"\\vspace{{6pt}}{tex(r['summary'])}\\par\n"
            f"\\begin{{minipage}}[t]{{0.64\\textwidth}}{left}\\end{{minipage}}\\hfill\n"
            f"\\begin{{minipage}}[t]{{0.30\\textwidth}}{right}\\end{{minipage}}")
    return _latex(pre, body)


def latex_classic(r: dict) -> str:
    c = r["contact"]
    pre = ("\\usepackage[margin=2.2cm]{geometry}\\usepackage{mathpazo}\n"
           "\\newcommand{\\cvsec}[1]{\\par\\vspace{10pt}{\\scshape\\large #1}\\\\[-4pt]\\rule{\\linewidth}{0.4pt}\\par\\vspace{2pt}}")
    jobs = _jobs_tex(r, lambda j: f"\\textbf{{{tex(j['role'])}}}, \\textit{{{tex(j['company'])}}}\\hfill {tex(j['dates'])}")
    body = (f"\\begin{{center}}{{\\Huge\\scshape {tex(r['name'])}}}\\\\[4pt]{tex(c['phone'])} $\\cdot$ {tex(c['email'])}"
            f" $\\cdot$ {tex(c['location'])}\\end{{center}}\n\\cvsec{{Profile}}\n{tex(r['summary'])}\n\\cvsec{{Experience}}\n{jobs}\n"
            "\\cvsec{Education}\n" + "\\\\\n".join(f"\\textbf{{{tex(x['degree'])}}}, {tex(x['school'])}\\hfill {tex(x['dates'])}" for x in r["education"])
            + "\n\\cvsec{Skills}\n" + tex(", ".join(r["skills"])) + "\n\\cvsec{Languages}\n" + tex(", ".join(r["languages"])))
    for h, items in _sections(r):
        body += f"\n\\cvsec{{{tex(h)}}}\n" + tex("; ".join(items))
    return _latex(pre, body)


def latex_two_column(r: dict) -> str:
    c = r["contact"]
    pre = ("\\usepackage[margin=1.5cm]{geometry}\\usepackage{lmodern}\\definecolor{rule}{HTML}{8B1E3F}\n"
           "\\newcommand{\\cvsec}[1]{\\par\\vspace{6pt}{\\bfseries\\color{rule}#1}\\par\\vspace{1pt}\\hrule\\vspace{3pt}}")
    jobs = _jobs_tex(r, lambda j: f"\\textbf{{{tex(j['role'])}}}\\\\{tex(j['company'])} ({tex(j['dates'])})", "--")
    left = "\\cvsec{Profile}\n" + tex(r["summary"]) + "\n\\cvsec{Experience}\n" + jobs
    right = ("\\cvsec{Contact}\n" + "\\\\\n".join(tex(v) for v in c.values()) + "\n\\cvsec{Education}\n"
             + "\\\\[3pt]\n".join(f"\\textbf{{{tex(x['degree'])}}}\\\\{tex(x['school'])}" for x in r["education"])
             + "\n\\cvsec{Skills}\n" + "\\\\\n".join(tex(s) for s in r["skills"]))
    for h, items in _sections(r):
        left += f"\n\\cvsec{{{tex(h)}}}\n" + tex("; ".join(items))
    body = (f"{{\\Huge\\bfseries {tex(r['name'])}}}\\hfill{{\\large\\color{{rule}} {tex(r['title'])}}}\\par\\vspace{{4pt}}\\hrule\n"
            f"\\begin{{minipage}}[t]{{0.66\\textwidth}}{left}\\end{{minipage}}\\hfill\n"
            f"\\begin{{minipage}}[t]{{0.29\\textwidth}}{right}\\end{{minipage}}")
    return _latex(pre, body)


def latex_sidebar(r: dict) -> str:
    c = r["contact"]
    pre = ("\\usepackage[margin=0cm,top=1.2cm,bottom=1.2cm]{geometry}\\usepackage{helvet}\\renewcommand\\familydefault{\\sfdefault}\n"
           "\\definecolor{side}{HTML}{22313F}\\definecolor{hi}{HTML}{F2A65A}\n"
           "\\newcommand{\\cvsec}[1]{\\par\\vspace{8pt}{\\bfseries\\color{hi}\\MakeUppercase{#1}}\\par}")
    side = ("\\colorbox{side}{\\parbox[t][26cm][t]{5.6cm}{\\color{white}\\vspace{8pt}\\hspace{4pt}\\parbox{4.8cm}{"
            f"{{\\Large\\bfseries {tex(r['name'])}}}\\par\n{tex(r['title'])}\\par\n\\cvsec{{Contact}}\n"
            + "\\\\\n".join(tex(v) for v in c.values()) + "\n\\cvsec{Skills}\n" + "\\\\\n".join(tex(s) for s in r["skills"])
            + "\n\\cvsec{Languages}\n" + "\\\\\n".join(tex(s) for s in r["languages"]) + "}}}")
    main = ("{\\bfseries\\large Profile}\\par\n" + tex(r["summary"]) + "\n\\vspace{8pt}{\\bfseries\\large Experience}\\par\n"
            + _jobs_tex(r, lambda j: f"\\textbf{{{tex(j['role'])}}}, {tex(j['company'])}\\hfill{{\\small {tex(j['dates'])}}}")
            + "\n\\vspace{8pt}{\\bfseries\\large Education}\\par\n"
            + "\\\\\n".join(f"{tex(x['degree'])}, {tex(x['school'])} ({tex(x['dates'])})" for x in r["education"]))
    for h, items in _sections(r):
        main += f"\n\\vspace{{8pt}}{{\\bfseries\\large {tex(h)}}}\\par\n" + tex("; ".join(items))
    return _latex(pre, f"\\noindent{side}\\hspace{{0.8cm}}\\begin{{minipage}}[t]{{12.2cm}}\\vspace{{0pt}}{main}\\end{{minipage}}")


# ---------- HTML designs (printed by Chromium; macOS system fonts, noted in the write-up) ----------

def _html(css: str, body: str) -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>@page{{size:A4;margin:0}}"
            f"*{{box-sizing:border-box}}body{{margin:0}}{css}</style></head><body>{body}</body></html>")


def _jobs_html(r, cls="job"):
    return "".join(
        f"<div class='{cls}'><div class='row'><b>{e(j['role'])}</b><span class='dates'>{e(j['dates'])}</span></div>"
        f"<div class='co'>{e(j['company'])}</div><ul>{''.join(f'<li>{e(b)}</li>' for b in j['bullets'])}</ul></div>"
        for j in r["experience"])


def _extra_html(r, tag="h2"):
    return "".join(f"<{tag}>{e(h)}</{tag}><p>{e('; '.join(i))}</p>" for h, i in _sections(r))


def html_word_two_column(r: dict) -> str:
    c = r["contact"]
    css = ("body{font:10.5pt Calibri,'Helvetica Neue',Arial,sans-serif;color:#222;padding:40px}h1{font-size:26pt;margin:0;color:#1F3864}"
           "h2{font-size:12pt;color:#1F3864;border-bottom:1.5px solid #1F3864;margin:14px 0 6px;text-transform:uppercase}"
           ".cols{display:flex;gap:28px}.main{flex:2}.side{flex:1}.row{display:flex;justify-content:space-between}"
           ".co{color:#555;font-style:italic}ul{margin:4px 0 8px;padding-left:18px}.dates{color:#555}")
    side = (f"<h2>Contact</h2>{''.join(f'<div>{e(v)}</div>' for v in c.values())}<h2>Skills</h2>"
            f"{''.join(f'<div>{e(s)}</div>' for s in r['skills'])}<h2>Languages</h2>{''.join(f'<div>{e(s)}</div>' for s in r['languages'])}")
    main = (f"<h2>Profile</h2><p>{e(r['summary'])}</p><h2>Experience</h2>{_jobs_html(r)}<h2>Education</h2>"
            + "".join(f"<div><b>{e(x['degree'])}</b>, {e(x['school'])} <span class='dates'>{e(x['dates'])}</span></div>" for x in r["education"])
            + _extra_html(r))
    return _html(css, f"<h1>{e(r['name'])}</h1><div>{e(r['title'])}</div><div class='cols'><div class='main'>{main}</div><div class='side'>{side}</div></div>")


_ICONS = {"phone": "M2 4h6l2 5-3 2a14 14 0 0 0 6 6l2-3 5 2v6a3 3 0 0 1-3 3A20 20 0 0 1 2 7a3 3 0 0 1 0-3z",
          "email": "M2 4h20v16H2zM2 5l10 8 10-8", "web": "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zM2 12h20M12 2c4 4 4 16 0 20",
          "location": "M12 2a7 7 0 0 0-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 0 0-7-7zM12 7a2 2 0 1 0 0 4 2 2 0 0 0 0-4z"}


def _icon(kind, color):
    return (f"<svg width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='{color}' stroke-width='2' "
            f"style='vertical-align:-2px;margin-right:6px'><path d='{_ICONS[kind]}'/></svg>")


def html_canva_icons(r: dict) -> str:
    c = r["contact"]
    css = ("body{font:10pt 'Avenir Next','Helvetica Neue',Arial,sans-serif;color:#2b2b2b;display:flex;min-height:297mm}"
           ".side{width:72mm;background:#E8625A;color:#fff;padding:36px 22px}.main{flex:1;padding:36px 30px}"
           "h1{font:700 24pt Georgia,serif;margin:0 0 4px}h2{font-size:11pt;letter-spacing:2px;text-transform:uppercase;margin:18px 0 6px}"
           ".side h2{border-bottom:1px solid #fff9}.main h2{color:#E8625A}.row{display:flex;justify-content:space-between}"
           ".co{color:#777}ul{padding-left:16px;margin:4px 0 8px}.chip{display:inline-block;background:#fff3;border-radius:10px;padding:2px 9px;margin:2px 2px 0 0}")
    side = (f"<h1>{e(r['name'])}</h1><div>{e(r['title'])}</div><h2>Contact</h2>"
            + "".join(f"<div style='margin:4px 0'>{_icon(k, '#fff')}{e(v)}</div>" for k, v in c.items())
            + "<h2>Skills</h2>" + "".join(f"<span class='chip'>{e(s)}</span>" for s in r["skills"])
            + "<h2>Languages</h2>" + "".join(f"<div>{e(s)}</div>" for s in r["languages"]))
    main = (f"<h2>About me</h2><p>{e(r['summary'])}</p><h2>Experience</h2>{_jobs_html(r)}<h2>Education</h2>"
            + "".join(f"<div><b>{e(x['degree'])}</b><br>{e(x['school'])}, {e(x['dates'])}</div>" for x in r["education"]) + _extra_html(r))
    return _html(css, f"<div class='side'>{side}</div><div class='main'>{main}</div>")


def html_plain_single(r: dict) -> str:
    c = r["contact"]
    css = ("body{font:11pt Georgia,'Times New Roman',serif;color:#111;padding:48px 56px}h1{font-size:22pt;margin:0;text-align:center}"
           ".contact{text-align:center;color:#444;margin-bottom:10px}h2{font-size:12pt;border-bottom:1px solid #111;margin:16px 0 6px}"
           ".row{display:flex;justify-content:space-between}ul{margin:3px 0 8px;padding-left:20px}.co{font-style:italic}")
    body = (f"<h1>{e(r['name'])}</h1><div class='contact'>{e(' | '.join(c.values()))}</div><h2>Summary</h2><p>{e(r['summary'])}</p>"
            f"<h2>Experience</h2>{_jobs_html(r)}<h2>Education</h2>"
            + "".join(f"<div class='row'><span><b>{e(x['degree'])}</b>, {e(x['school'])}</span><span>{e(x['dates'])}</span></div>" for x in r["education"])
            + f"<h2>Skills</h2><p>{e(', '.join(r['skills']))}</p><h2>Languages</h2><p>{e(', '.join(r['languages']))}</p>" + _extra_html(r))
    return _html(css, body)


def html_banner_timeline(r: dict) -> str:
    c = r["contact"]
    css = ("body{font:10pt 'Helvetica Neue',Arial,sans-serif;color:#1d2b36}.banner{background:#14532D;color:#fff;padding:34px 44px}"
           "h1{margin:0;font-size:28pt;font-weight:300;letter-spacing:1px}.sub{color:#BBF7D0}.wrap{padding:16px 44px}"
           "h2{font-size:11pt;color:#14532D;text-transform:uppercase;letter-spacing:1.5px;margin:16px 0 6px}"
           ".job{border-left:3px solid #86EFAC;padding-left:14px;margin-bottom:10px}.row{display:flex;justify-content:space-between}"
           ".co{color:#4b5d6b}ul{padding-left:16px;margin:3px 0}.tags span{border:1px solid #14532D;border-radius:3px;padding:1px 7px;margin-right:4px;display:inline-block;margin-bottom:4px}")
    body = (f"<div class='banner'><h1>{e(r['name'])}</h1><div class='sub'>{e(r['title'])} &middot; {e(c['email'])} &middot; {e(c['phone'])} &middot; {e(c['location'])}</div></div>"
            f"<div class='wrap'><h2>Profile</h2><p>{e(r['summary'])}</p><h2>Experience</h2>{_jobs_html(r)}<h2>Education</h2>"
            + "".join(f"<div><b>{e(x['degree'])}</b>, {e(x['school'])}, {e(x['dates'])}</div>" for x in r["education"])
            + "<h2>Skills</h2><div class='tags'>" + "".join(f"<span>{e(s)}</span>" for s in r["skills"]) + "</div>"
            + f"<h2>Languages</h2><p>{e(', '.join(r['languages']))}</p>" + _extra_html(r) + "</div>")
    return _html(css, body)


DESIGNS = [
    ("latex-altacv", "latex", latex_altacv), ("latex-classic", "latex", latex_classic),
    ("latex-two-column", "latex", latex_two_column), ("latex-sidebar", "latex", latex_sidebar),
    ("html-word-two-column", "html", html_word_two_column), ("html-canva-icons", "html", html_canva_icons),
    ("html-plain-single", "html", html_plain_single), ("html-banner-timeline", "html", html_banner_timeline),
]


def source(n: int, r: dict | None = None) -> tuple[str, str, str]:
    """(design id, kind, source text) of CV number *n*, from its own record unless *r* is given."""
    design, kind, fn = DESIGNS[n - 1]
    return design, kind, fn(r or record(n))
