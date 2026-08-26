import numpy as np
import pytest
from beatscope.structure import (
    cosine_similarity,
    build_bar_vector,
    analyze_song_structure,
)


def test_cosine_similarity():
    v1 = np.array([1.0, 0.0, 0.0])
    v2 = np.array([1.0, 0.0, 0.0])
    v3 = np.array([0.0, 1.0, 0.0])
    assert abs(cosine_similarity(v1, v2) - 1.0) < 1e-6
    assert abs(cosine_similarity(v1, v3) - 0.0) < 1e-6


def test_structure_break_and_repeat():
    beats = [
        {"time": 0.0, "beat": 1, "bar": 1, "downbeat": True, "sequence_gap": False},
        {"time": 0.5, "beat": 2, "bar": 1, "downbeat": False, "sequence_gap": False},
        {"time": 1.0, "beat": 3, "bar": 1, "downbeat": False, "sequence_gap": False},
        {"time": 1.5, "beat": 4, "bar": 1, "downbeat": False, "sequence_gap": False},
        {"time": 2.0, "beat": 1, "bar": 2, "downbeat": True, "sequence_gap": False},
        {"time": 2.5, "beat": 2, "bar": 2, "downbeat": False, "sequence_gap": False},
        {"time": 3.0, "beat": 3, "bar": 2, "downbeat": False, "sequence_gap": False},
        {"time": 3.5, "beat": 4, "bar": 2, "downbeat": False, "sequence_gap": False},
        {"time": 4.0, "beat": 1, "bar": 3, "downbeat": True, "sequence_gap": False},
        {"time": 4.5, "beat": 2, "bar": 3, "downbeat": False, "sequence_gap": False},
        {"time": 5.0, "beat": 3, "bar": 3, "downbeat": False, "sequence_gap": False},
        {"time": 5.5, "beat": 4, "bar": 3, "downbeat": False, "sequence_gap": False},
    ]

    # Bar 1 and Bar 2 have same onsets
    onsets = [
        {"raw_time": 0.0, "strength": 0.8, "bands": {"all": 0.8, "low": 0.7, "mid": 0.1, "high": 0.0}},
        {"raw_time": 1.0, "strength": 0.6, "bands": {"all": 0.6, "low": 0.1, "mid": 0.5, "high": 0.1}},
        {"raw_time": 2.0, "strength": 0.8, "bands": {"all": 0.8, "low": 0.7, "mid": 0.1, "high": 0.0}},
        {"raw_time": 3.0, "strength": 0.6, "bands": {"all": 0.6, "low": 0.1, "mid": 0.5, "high": 0.1}},
        # Bar 3 has almost no onsets (break)
    ]

    structure = analyze_song_structure(onsets, beats, bars=3, subdivision=16)
    assert len(structure) == 3
    assert structure[0]["group"] == "A"
    assert structure[1]["group"] == "A"
    assert structure[1]["label"] == "repeat"
    assert structure[2]["group"] == "BREAK"
    assert structure[2]["label"] == "break"
