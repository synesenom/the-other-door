"""Offline check of the #326 acceptance: an English and a Danish ad with an explicit
no-sponsorship line are condensed (the line survives), flagged, and zeroed for a
candidate who sets ``needs_work_permit`` (stubbed scorer reply, no model call)."""

import pytest

from door.matching import scorer
from door.matching.condense import condense_description

_ADS = {
    "en": "We are unable to offer visa sponsorship for this role.",
    "da": "Vi kan ikke tilbyde sponsorering af arbejdstilladelse.",
    "fr": "Nous ne pouvons pas sponsoriser de visa pour ce poste.",
}


def _posting(language):
    filler = "\n".join(f"Vi arbejder med ting nummer {i} hver dag." for i in range(60))
    description = f"{filler}\n{_ADS[language]}\n{filler}"
    condensed = condense_description(description, max_chars=300, language=language)
    return {"id": f"x-{language}", "description": description, "description_condensed": condensed}


@pytest.mark.parametrize("language", ["en", "da", "fr"])
def test_ad_with_no_sponsorship_line_is_flagged_and_zeroed_only_for_those_who_need_a_permit(language):
    posting = _posting(language)
    assert _ADS[language] in posting["description_condensed"]
    reply = {"score": 0.8, "score_reason": "good fit", "work_permit": "no_sponsorship"}

    needing = scorer.apply_result(posting, reply, needs_work_permit=True)
    assert needing["work_permit"] == "no_sponsorship"
    assert needing["score"] == 0.0

    other = scorer.apply_result(posting, reply)
    assert other["work_permit"] == "no_sponsorship"
    assert other["score"] == 0.8
