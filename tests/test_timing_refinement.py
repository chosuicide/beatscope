"""Round 1 of the refinement layer: move, or leave exactly alone.

The contract worth testing is the one the plan sets out: every beat keeps the
"do not move" option, a move needs evidence and a margin, order and spacing are
never violated, and nothing about the layer assumes a tempo or a metre.
"""
from __future__ import annotations

import numpy as np
import pytest

from beatscope.timing_refinement import (
    local_period,
    onset_evidence,
    refine_beats,
    support_at,
)


def test_a_beat_with_no_evidence_does_not_move():
    beats = [0.0, 0.5, 1.0, 1.5, 2.0]
    refined, records = refine_beats(beats, onsets=[], support=None)
    assert refined == beats
    assert all(not record.moved for record in records)
    assert all(record.reason in ("stay", "no-local-period") for record in records)


def test_a_beat_moves_onto_a_clear_onset():
    beats = [0.0, 0.5, 1.0, 1.5, 2.0]
    # One beat is 40 ms early against a clear attack, the rest agree.
    onsets = [0.0, 0.5, 1.04, 1.5, 2.0]
    refined, records = refine_beats(beats, onsets=onsets, support=None, margin=0.15)
    assert refined[2] == pytest.approx(1.04, abs=1e-9)
    assert records[2].moved and records[2].reason == "moved"
    assert refined[:2] == beats[:2] and refined[3:] == beats[3:]


def test_a_syncopation_inside_the_window_does_not_drag_a_beat_away():
    """A loud off-beat event is not automatically a beat."""
    beats = [0.0, 0.5, 1.0, 1.5, 2.0]
    # An onset halfway between two beats: 0.25 s away, well outside tolerance.
    refined, _ = refine_beats(beats, onsets=[0.25, 0.75, 1.25, 1.75], support=None)
    assert refined == beats


def test_moving_needs_the_margin_not_just_a_better_score():
    beats = [0.0, 0.5, 1.0, 1.5, 2.0]
    onsets = [0.0, 0.5, 1.02, 1.5, 2.0]  # a weak overlap, 20 ms off
    strict, _ = refine_beats(beats, onsets=onsets, support=None, margin=0.9)
    lenient, _ = refine_beats(beats, onsets=onsets, support=None, margin=0.01)
    assert strict[2] == 1.0, "a high margin refuses a small gain"
    assert lenient[2] == pytest.approx(1.02, abs=1e-9)


def test_the_model_support_curve_can_attract_a_beat_on_its_own():
    beats = [0.0, 0.5, 1.0, 1.5, 2.0]
    support = np.zeros(150)  # 50 fps over 3 s
    support[int(1.06 * 50)] = 1.0  # a support peak 60 ms after the beat
    refined, records = refine_beats(beats, onsets=[], support=support, margin=0.05)
    assert refined[2] == pytest.approx(1.06, abs=0.03)
    assert records[2].moved


def test_order_and_spacing_survive_even_with_conflicting_evidence():
    """Two beats cannot be pulled onto the same event, and cannot cross."""
    beats = [0.0, 0.5, 1.0, 1.5, 2.0]
    onsets = [0.5, 0.52, 1.0]  # two onsets between beats 1 and 2
    refined, _ = refine_beats(beats, onsets=onsets, support=None, margin=0.01)
    assert refined == sorted(refined), "refinement must not invert beats"
    assert all(b - a > 0 for a, b in zip(refined, refined[1:], strict=False)), "nor collide"


def test_local_period_uses_neighbours_only():
    times = [0.0, 0.5, 1.0, 2.0, 2.5]
    assert local_period(times, 0) == 0.5
    assert local_period(times, 1) == 0.5
    assert local_period(times, 3) == pytest.approx(0.75), "a tempo change is local, not global"
    assert local_period([1.0], 0) == 0.0


def test_a_tempo_change_is_not_treated_as_an_error():
    """No global grid: each beat is judged against its own neighbourhood."""
    beats = [0.0, 0.5, 1.0, 2.0, 3.0]  # halves, then wholes
    refined, records = refine_beats(beats, onsets=[], support=None)
    assert refined == beats
    assert all(not record.moved for record in records)


def test_helpers_are_bounded():
    assert onset_evidence([1.0], 1.0, 0.05) == 1.0
    assert onset_evidence([1.0], 1.06, 0.05) == 0.0
    assert 0.0 <= onset_evidence([1.0], 1.025, 0.05) <= 1.0
    support = np.array([0.0, 1.0, 0.0])
    assert support_at(support, 1.0, 1.0) == 1.0
    assert support_at(support, 1.0, -1.0) == 0.0
    assert support_at(support, 1.0, 99.0) == 0.0
