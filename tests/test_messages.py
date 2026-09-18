"""The message table: one home for the strings a user reads.

The product ships English first with Chinese behind the studio's language
switch, so the table must carry both columns for every key - a key that only
exists in one language is a half-finished translation, not a shortcut.
"""
import re

import pytest

from beatscope.jobs import Job
from beatscope.messages import _TEXT, LANGUAGES, msg

PLACEHOLDER = re.compile(r"\{(\w+)\}")


@pytest.mark.parametrize("key", sorted(_TEXT))
def test_every_key_carries_both_languages(key):
    for language in LANGUAGES:
        value = _TEXT[key].get(language)
        assert isinstance(value, str) and value.strip(), f"{key} is missing {language}"


@pytest.mark.parametrize("key", sorted(_TEXT))
def test_both_languages_fill_the_same_fields(key):
    """A placeholder that only one column has would raise at the call site."""
    fields = {language: set(PLACEHOLDER.findall(_TEXT[key][language])) for language in LANGUAGES}
    assert len(set(map(frozenset, fields.values()))) == 1, f"{key} placeholders differ: {fields}"


def test_english_is_the_default_language():
    assert msg("job.queued") == "Job queued"
    assert Job(id="0" * 12).message == "Job queued"


def test_fields_are_filled_in():
    assert msg("job.failed", error="disk full") == "Analysis failed: disk full"
    assert msg("job.queued-position", position=2) == "Queued (position 2)"


def test_an_unknown_key_is_a_programming_error():
    with pytest.raises(KeyError):
        msg("job.never-defined")
