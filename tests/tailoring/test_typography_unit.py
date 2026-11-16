"""French typography at compile time (#146, #143): a narrow no-break space before : ; ! ? and inside guillemets,
in the text only, never in a link, an address or an identifier. The tailor writes plain punctuation."""

from door.tailoring import typography

NB = " "


def fr(html: str) -> str:
    return typography.apply(html, "fr")


def test_a_narrow_no_break_space_stands_before_the_four_marks():
    assert fr("<p>Compétences : Python ; SQL ! Vraiment ? Oui.</p>") == (
        f"<p>Compétences{NB}: Python{NB}; SQL{NB}! Vraiment{NB}? Oui.</p>")
    assert fr("<p>Compétences: Python</p>") == f"<p>Compétences{NB}: Python</p>"


def test_the_space_that_was_there_is_replaced_not_doubled():
    assert fr("<p>a : b</p>") == f"<p>a{NB}: b</p>"
    assert fr("<p>a : b</p>") == f"<p>a{NB}: b</p>"


def test_guillemets_get_a_space_inside():
    assert fr("<p>Il a dit «bonjour» puis « salut ».</p>") == (
        f"<p>Il a dit «{NB}bonjour{NB}» puis «{NB}salut{NB}».</p>")
    assert fr("<p>&laquo;x&raquo;</p>") == f"<p>«{NB}x{NB}»</p>"


def test_an_identifier_a_time_or_an_address_is_left_alone():
    for text in ("arXiv:2408.10754", "rendez-vous à 10:30", "https://example.com/a?b=c", "a?b=c", "ratio 3:1",
                 "mailto:ada@example.com"):
        assert fr(f"<p>{text}</p>") == f"<p>{text}</p>", text


def test_a_link_its_attributes_and_comments_are_left_alone():
    html = '<!-- Keywords: a : b --><p><a href="https://x.example/?q=1 :">doi: 10.1 ; x</a> : fin</p>'
    assert fr(html) == '<!-- Keywords: a : b --><p><a href="https://x.example/?q=1 :">doi: 10.1 ; x</a>' + NB + ": fin</p>"


def test_an_entity_is_not_a_semicolon():
    assert fr("<p>R&amp; D &lt; x</p>") == "<p>R&amp; D &lt; x</p>"


def test_a_mark_across_a_tag_boundary():
    assert fr("<p><strong>Langues</strong>: français</p>") == f"<p><strong>Langues</strong>{NB}: français</p>"


def test_it_is_idempotent():
    once = fr("<p>Compétences : « x » !</p>")
    assert fr(once) == once


def test_other_languages_are_unchanged():
    text = "<p>Skills : « x » ! ?</p>"
    assert typography.apply(text, "en") == text
    assert typography.apply(text, "da") == text
