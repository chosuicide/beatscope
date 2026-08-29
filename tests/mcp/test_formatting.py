"""Unit tests for output shaping helpers (plan section 10)."""
import pytest

from beatscope.mcp.formatting import (
    finite_or_none,
    full_or_truncated,
    paginate,
    project_summary,
    provenance_methods,
    summary_line,
    timing_view,
)

MINIMAL = {
    "tempo": {"global_bpm": 98.7654},
    "grid": {"bars": 4},
    "source": {"display_name": "demo.wav", "duration": 12.3456},
    "analysis": {
        "backend": "beat-this",
        "pipeline_version": "0.4.0",
        "warnings": ["w1"],
        "provenance": {"beats": {"method": "beat-this-markers"}, "junk": "not-a-dict"},
    },
    "beats": [{"time": 0.0}] * 4,
    "onsets": [{"id": i} for i in range(6)],
    "cues": {"accent": [{"time": 0.5}], "impact": [], "scale": [{"time": 1.0}]},
}


def test_project_summary_counts_and_rounds():
    summary = project_summary("0a1b2c3d4e5f", MINIMAL)
    assert summary["bpm"] == 98.77  # round(x, 2)
    assert summary["duration"] == 12.346
    assert summary["bars"] == 4
    assert summary["beats"] == 4
    assert summary["onsets"] == 6
    assert summary["cues"] == 2
    assert summary["warnings"] == ["w1"]
    assert summary["provenance"] == {"beats": "beat-this-markers"}
    assert summary["backend"] == "beat-this"


def test_project_summary_tolerates_missing_sections():
    summary = project_summary("0a1b2c3d4e5f", {})
    assert summary["bpm"] is None
    assert summary["display_name"] == "unknown"
    assert summary["bars"] == 0
    assert summary["cues"] == 0
    assert summary["provenance"] == {}


def test_summary_line_formats():
    line = summary_line(project_summary("0a1b2c3d4e5f", MINIMAL))
    assert line == "98.77 BPM · 4 bars · 12.35 s · backend beat-this"
    sparse = summary_line(project_summary("0a1b2c3d4e5f", {}))
    assert sparse == "0 bars"


def test_timing_view_never_carries_energy():
    rhythm = {**MINIMAL, "energy": {"fps": 100, "bands": {"all": [0.1]}}}
    view = timing_view(rhythm)
    assert "energy" not in view
    assert view["tempo"]["global_bpm"] == 98.7654
    assert len(view["beats"]) == 4
    assert "meter" not in view  # absent sections are dropped, not null-filled


def test_paginate_metadata():
    items = list(range(5))
    page, meta = paginate(items, limit=2, offset=2)
    assert page == [2, 3]
    assert meta == {"total": 5, "count": 2, "offset": 2, "has_more": True, "next_offset": 4}
    last, meta = paginate(items, limit=2, offset=4)
    assert (last, meta["has_more"], meta["next_offset"]) == ([4], False, None)
    empty, meta = paginate([], limit=2, offset=0)
    assert (empty, meta["total"], meta["count"], meta["has_more"]) == ([], 0, 0, False)


def test_full_or_truncated_never_cuts_json():
    small = {"a": 1}
    payload, truncated = full_or_truncated(small, max_chars=1000)
    assert (payload, truncated) == (small, False)
    big = {"pad": "x" * 200}
    payload, truncated = full_or_truncated(big, max_chars=50)
    assert payload is None
    assert truncated is True


def test_full_or_truncated_rejects_non_finite():
    with pytest.raises(ValueError):
        full_or_truncated({"x": float("inf")}, max_chars=1000)


def test_finite_or_none():
    assert finite_or_none(float("inf")) is None
    assert finite_or_none(float("nan")) is None
    assert finite_or_none(1.5) == 1.5
    assert finite_or_none("x") == "x"
