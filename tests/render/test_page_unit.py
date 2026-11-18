"""`render/page.py`: a body placed in a template's columns (#147), its photo and its print (#355)."""

from door.render import page


def test_a_heading_inside_the_header_stays_in_the_header_and_the_columns_start_after_it():
    """#242: a header with its own <h2> (a built style's sample body put CONTACT there) is not split: splitting at it
    left the columns inside the header, which the template places in its own grid area."""
    from door.core import templates
    body = ('<header class="cv-header"><h1>A B</h1><h2>Contact</h2><p class="contact">x</p></header>'
            "<h2>Experience</h2><p>e</p><h2>Skills</h2><p>s</p>")
    placed = page.place_columns(body, templates.Columns(side=["skills"]))
    head, rest = placed.split("</header>", 1)
    assert "<h2>Contact</h2>" in head and '<div class="main">' not in head
    assert rest == '<div class="main"><h2>Experience</h2><p>e</p></div><div class="side"><h2>Skills</h2><p>s</p></div>'
